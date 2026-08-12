import socket
from datetime import timedelta
from unittest.mock import ANY, Mock, patch

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from applications.models import App
from config.asgi import application
from core.apps.mixins import AppMixin
from core.apps.mixins.apps import interactive_run
from core.apps.mixins.apps.interactive_run import (
    create_interactive_audit_chunk,
    get_interactive_driver,
    submit_interactive_session_answer,
)
from core.apps.mixins.apps.run_data import (
    build_loaddata_command,
    build_migrate_command,
    validate_dump_args,
    validate_loaddata_fixture_path,
    validate_manage_path,
)
from core.apps.mixins.services.service_dokku import initialize_dokku_service
from identity.models import CLIToken, User
from infrastructure.adapters.dokku_mixins.dokku_apps import DokkuAppsMixin
from infrastructure.adapters.dokku_mixins.dokku_config import DokkuConfigMixin
from infrastructure.adapters.dokku_mixins.dokku_git import DokkuGitMixin
from infrastructure.adapters.dokku_mixins.dokku_postgres import DokkuPostgresMixin
from infrastructure.adapters.git_utils import build_github_auth_url, mask_git_credentials, parse_github_repo_name
from infrastructure.adapters.ssh import SSHAdapter
from infrastructure.cache_versioning import APP_LAST_COMMIT_CACHE_NAMESPACE, get_cache_ttl
from interactive_sessions.interactive_crypto import decrypt_interactive_text
from interactive_sessions.interactive_runner import claim_pending_interactive_sessions, has_live_interactive_runner
from interactive_sessions.models import (
    InteractiveRunAuditChunk,
    InteractiveRunAuditDirection,
    InteractiveRunCommandKind,
    InteractiveRunEvent,
    InteractiveRunEventType,
    InteractiveRunRunner,
    InteractiveRunSession,
    InteractiveRunSessionStatus,
)
from observability.models import redact_sensitive_log_message
from projects.models import Project
from service_mgmt.models import Service
from service_mgmt.service_types import get_service_runtime
from tests.fakes import FakeInteractiveChannel


class RecordingPostgresAdapter(DokkuPostgresMixin):
    def __init__(self):
        self.commands = []
        self.stdin_calls = []

    def _run_command(self, command):
        self.commands.append(command)
        return 'ok'

    def _run_command_with_stdin(self, command, stdin_data):
        self.stdin_calls.append((command, stdin_data))
        return ' postgis_version\n-----------------\n 3.5 USE_GEOS=1\n'


class PostGISAdapterTests(SimpleTestCase):
    def test_create_database_uses_configured_postgis_image(self):
        adapter = RecordingPostgresAdapter()

        adapter.create_database(
            'mapas-db',
            'secret',
            image='postgis/postgis',
            image_version='17-3.5',
        )

        self.assertEqual(
            adapter.commands,
            ['postgres:create mapas-db -p secret --image postgis/postgis --image-version 17-3.5'],
        )

    def test_initialize_postgis_enables_and_validates_extension(self):
        adapter = RecordingPostgresAdapter()

        result = initialize_dokku_service(adapter, get_service_runtime('postgis'), 'mapas-db')

        self.assertIsNotNone(result)
        self.assertEqual(adapter.stdin_calls[0][0], 'postgres:connect mapas-db')
        self.assertIn('CREATE EXTENSION IF NOT EXISTS postgis;', adapter.stdin_calls[0][1])
        self.assertIn('SELECT PostGIS_Version();', adapter.stdin_calls[0][1])


class FakeConfigAdapter(DokkuConfigMixin):
    def __init__(self):
        self.commands = []

    def _run_command(self, command: str) -> str:
        self.commands.append(command)
        return 'OK'


class FakeAppsAdapter(DokkuAppsMixin):
    def __init__(self, output: str):
        self.output = output

    def _run_command(self, command: str) -> str:
        return self.output


class FakeGitAdapter(DokkuGitMixin):
    def __init__(self, output_lines):
        self.output_lines = output_lines

    def _run_command(self, command: str) -> str:
        return '\n'.join(self.output_lines)

    def _run_command_streaming(self, command: str):
        yield from self.output_lines

    def exists_app(self, app_name: str) -> bool:
        return True


class GitUrlUtilsTests(SimpleTestCase):
    def test_parse_and_mask_authenticated_github_url(self):
        git_url = 'https://x-access-token:secret-token@github.com/org/private-repo.git'

        assert parse_github_repo_name(git_url) == 'org/private-repo'
        assert mask_git_credentials(git_url) == 'https://***@github.com/org/private-repo.git'
        assert (
            mask_git_credentials(f'Cloning from {git_url}')
            == 'Cloning from https://***@github.com/org/private-repo.git'
        )

    def test_build_github_auth_url_normalizes_https_url(self):
        assert (
            build_github_auth_url('https://github.com/org/private-repo', 'secret-token')
            == 'https://x-access-token:secret-token@github.com/org/private-repo.git'
        )


class CacheVersioningTests(SimpleTestCase):
    @override_settings(CACHE_TTL_DEFAULT=45)
    def test_get_cache_ttl_uses_global_default_for_new_namespaces(self):
        self.assertEqual(get_cache_ttl('future-cache-namespace'), 45)

    @override_settings(CACHE_TTL_DEFAULT=45)
    def test_get_cache_ttl_uses_inline_default_when_provided(self):
        self.assertEqual(get_cache_ttl(APP_LAST_COMMIT_CACHE_NAMESPACE, default=300), 300)

    @override_settings(CACHE_TTL_DEFAULT=45)
    def test_get_cache_ttl_allows_namespace_env_override(self):
        with patch.dict('os.environ', {'CACHE_TTL_APP_LAST_COMMIT': '120'}):
            self.assertEqual(get_cache_ttl(APP_LAST_COMMIT_CACHE_NAMESPACE, default=300), 120)


class RunDataValidationTests(SimpleTestCase):
    def test_validate_manage_path_accepts_relative_manage_py(self):
        self.assertEqual(validate_manage_path('src/manage.py'), 'src/manage.py')

    def test_validate_manage_path_rejects_unsafe_paths(self):
        for value in ('/app/manage.py', '../manage.py', 'src/settings.py', 'C:/app/manage.py', 'src dir/manage.py'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_manage_path(value)

    def test_validate_dump_args_blocks_output_and_shell_operators(self):
        for args in (['--output', 'dump.json'], ['--output=dump.json'], ['auth.User', '&&', 'rm']):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    validate_dump_args(args)

    def test_validate_loaddata_fixture_path_accepts_relative_json(self):
        self.assertEqual(validate_loaddata_fixture_path('./fixtures/my_data.json'), 'fixtures/my_data.json')

    def test_validate_loaddata_fixture_path_rejects_unsafe_paths(self):
        for value in ('/tmp/data.json', '../data.json', 'fixture.yaml', 'C:/app/data.json', 'fixtures/my data.json'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_loaddata_fixture_path(value)

    def test_build_loaddata_command_uses_safe_paths_without_shell_script(self):
        command = build_loaddata_command('src/manage.py', 'fixtures/my_data.json')

        self.assertEqual(command, 'python src/manage.py loaddata fixtures/my_data.json')

    def test_build_migrate_command_supports_custom_manage_path(self):
        command = build_migrate_command('src/manage.py', noinput=True)

        self.assertEqual(command, 'python src/manage.py migrate --noinput')


class InteractiveRunValidationTests(SimpleTestCase):
    def test_createsuperuser_driver_matches_expected_prompts(self):
        driver = get_interactive_driver(InteractiveRunCommandKind.DJANGO_CREATESUPERUSER)

        samples = [
            ('Email address: ', 'email', False),
            ('Name: ', 'name', False),
            ('Password: ', 'password', True),
            ('Password (again): ', 'password_confirmation', True),
            (
                'Bypass password validation and create user anyway? [y/N]: ',
                'password_validation_bypass',
                False,
            ),
            (
                'Ignorar validação de senha e criar usuário mesmo assim? [s/N]: ',
                'password_validation_bypass',
                False,
            ),
        ]

        for prompt_text, prompt_key, is_secret in samples:
            with self.subTest(prompt_text=prompt_text):
                prompt_match = driver.match_prompt(prompt_text)
                self.assertIsNotNone(prompt_match)
                self.assertEqual(prompt_match.spec.key, prompt_key)
                self.assertEqual(prompt_match.spec.secret, is_secret)


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class InteractiveRunEndpointTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='interactive@example.com',
            password='senha123',
            name='Interactive User',
        )
        self.other_user = User.objects.create_user(
            email='interactive-other@example.com',
            password='senha123',
            name='Other Interactive User',
        )
        self.project = Project.objects.create(name='Projeto Interactive')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-interactive',
            name_dokku='app-interactive',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )
        self.runner = InteractiveRunRunner.objects.create(
            runner_id='runner-test',
            hostname='test-host',
            pid=123,
            max_sessions=5,
            active_sessions=0,
            last_heartbeat_at=timezone.now(),
        )
        self.client.force_authenticate(user=self.user)

    def test_create_interactive_session_waits_for_interactive_runner(self):
        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/',
            {'command_kind': 'django_createsuperuser', 'manage_path': 'src/manage.py'},
            format='json',
        )

        self.assertEqual(response.status_code, 202)
        self.assertIn('websocket_url', response.data)
        self.assertNotIn('task_id', response.data)
        session = InteractiveRunSession.objects.get(id=response.data['session_id'])
        self.assertEqual(session.status, InteractiveRunSessionStatus.PENDING)
        self.assertEqual(session.manage_path, 'src/manage.py')
        self.assertIsNone(session.task_id)

    def test_create_interactive_session_rejects_when_no_runner_is_alive(self):
        self.runner.delete()

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/',
            {'command_kind': 'django_createsuperuser', 'manage_path': 'src/manage.py'},
            format='json',
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn('runner interativo', response.data['error'])
        self.assertFalse(InteractiveRunSession.objects.exists())

    def test_create_postgres_connect_session_uses_linked_postgres_service(self):
        service = Service.objects.create(
            name='db-interactive',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=self.app,
            project=self.project,
            service_type='postgres',
            container_name='db-interactive',
        )

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/',
            {'command_kind': 'postgres_connect', 'service_id': service.id},
            format='json',
        )

        self.assertEqual(response.status_code, 202)
        self.assertIn('terminal_events', response.data['stream_url'])
        self.assertIn('websocket_url', response.data)
        session = InteractiveRunSession.objects.get(id=response.data['session_id'])
        self.assertEqual(session.command_kind, InteractiveRunCommandKind.POSTGRES_CONNECT)
        self.assertEqual(session.service_id, service.id)

    def test_create_postgres_connect_session_accepts_linked_postgis_service(self):
        service = Service.objects.create(
            name='postgis-interactive',
            user='postgres',
            password='secret',
            host='dokku-postgres-postgis-interactive',
            port=5432,
            app=self.app,
            project=self.project,
            service_type='postgis',
            container_name='postgis-interactive',
            env_key='DATABASE_URL',
            image='postgis/postgis',
            image_version='17-3.5',
        )

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/',
            {'command_kind': 'postgres_connect', 'service_id': service.id},
            format='json',
        )

        self.assertEqual(response.status_code, 202)
        session = InteractiveRunSession.objects.get(id=response.data['session_id'])
        self.assertEqual(session.service_id, service.id)

    def test_create_postgres_connect_session_rejects_non_postgres_service(self):
        service = Service.objects.create(
            name='redis-interactive',
            user='redis',
            password='',
            host='localhost',
            port=6379,
            app=self.app,
            project=self.project,
            service_type='redis',
            container_name='redis-interactive',
        )

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/',
            {'command_kind': 'postgres_connect', 'service_id': service.id},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_answer_endpoint_encrypts_pending_answer_without_storing_plaintext(self):
        session = InteractiveRunSession.objects.create(
            app=self.app,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
            status=InteractiveRunSessionStatus.AWAITING_INPUT,
            manage_path='manage.py',
            awaiting_prompt_id='email-1',
            awaiting_prompt_text='Email address:',
            awaiting_prompt_secret=False,
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/{session.id}/answer/',
            {'prompt_id': 'email-1', 'value': 'admin@example.com'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        encrypted_value = bytes(session.pending_answer_ciphertext)
        self.assertIsNotNone(session.pending_answer_ciphertext)
        self.assertNotIn(b'admin@example.com', encrypted_value)

    def test_answer_endpoint_rejects_invalid_prompt(self):
        session = InteractiveRunSession.objects.create(
            app=self.app,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
            status=InteractiveRunSessionStatus.AWAITING_INPUT,
            manage_path='manage.py',
            awaiting_prompt_id='email-1',
            awaiting_prompt_text='Email address:',
            awaiting_prompt_secret=False,
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/{session.id}/answer/',
            {'prompt_id': 'name-2', 'value': 'Admin'},
            format='json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn('prompt', response.data['error'].lower())

    def test_cancel_endpoint_marks_session_for_cancellation(self):
        session = InteractiveRunSession.objects.create(
            app=self.app,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
            status=InteractiveRunSessionStatus.RUNNING,
            manage_path='manage.py',
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )

        response = self.client.post(f'/api/apps/apps/{self.app.id}/interactive_sessions/{session.id}/cancel/')

        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertTrue(session.cancel_requested)

    def test_events_endpoint_streams_existing_events(self):
        session = InteractiveRunSession.objects.create(
            app=self.app,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
            status=InteractiveRunSessionStatus.COMPLETED,
            manage_path='manage.py',
            completed_at=timezone.now(),
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )
        InteractiveRunEvent.objects.create(
            session=session,
            event_type=InteractiveRunEventType.COMPLETE,
            payload={'message': 'Superusuario criado com sucesso.'},
        )

        response = self.client.get(f'/api/apps/apps/{self.app.id}/interactive_sessions/{session.id}/events/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/event-stream')
        streamed_content = b''.join(
            chunk if isinstance(chunk, bytes) else chunk.encode('utf-8')
            for chunk in response.streaming_content
        ).decode('utf-8')
        self.assertIn('event: complete', streamed_content)
        self.assertIn('Superusuario criado com sucesso.', streamed_content)

    def test_events_endpoint_accepts_sse_accept_header(self):
        session = InteractiveRunSession.objects.create(
            app=self.app,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
            status=InteractiveRunSessionStatus.COMPLETED,
            manage_path='manage.py',
            completed_at=timezone.now(),
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )
        InteractiveRunEvent.objects.create(
            session=session,
            event_type=InteractiveRunEventType.COMPLETE,
            payload={'message': 'Superusuario criado com sucesso.'},
        )

        response = self.client.get(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/{session.id}/events/',
            HTTP_ACCEPT='text/event-stream',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/event-stream')

    def test_other_user_cannot_access_foreign_session(self):
        session = InteractiveRunSession.objects.create(
            app=self.app,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
            status=InteractiveRunSessionStatus.AWAITING_INPUT,
            manage_path='manage.py',
            awaiting_prompt_id='email-1',
            awaiting_prompt_text='Email address:',
            awaiting_prompt_secret=False,
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )

        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/{session.id}/answer/',
            {'prompt_id': 'email-1', 'value': 'blocked@example.com'},
            format='json',
        )

        self.assertEqual(response.status_code, 404)

    def test_terminal_input_endpoint_stores_encrypted_audit_chunk(self):
        service = Service.objects.create(
            name='db-terminal-input',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=self.app,
            project=self.project,
            service_type='postgres',
            container_name='db-terminal-input',
        )
        session = InteractiveRunSession.objects.create(
            app=self.app,
            service=service,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.POSTGRES_CONNECT,
            status=InteractiveRunSessionStatus.RUNNING,
            manage_path='manage.py',
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/{session.id}/input/',
            {'data': 'SELECT 1;\n'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        chunk = InteractiveRunAuditChunk.objects.get(session=session)
        self.assertEqual(chunk.direction, InteractiveRunAuditDirection.INPUT)
        self.assertNotIn(b'SELECT 1', bytes(chunk.content_ciphertext))
        self.assertEqual(decrypt_interactive_text(chunk.content_ciphertext), 'SELECT 1;\n')

    def test_terminal_events_streams_audit_output_without_interactive_output_event(self):
        service = Service.objects.create(
            name='db-terminal-output',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=self.app,
            project=self.project,
            service_type='postgres',
            container_name='db-terminal-output',
        )
        session = InteractiveRunSession.objects.create(
            app=self.app,
            service=service,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.POSTGRES_CONNECT,
            status=InteractiveRunSessionStatus.COMPLETED,
            manage_path='manage.py',
            completed_at=timezone.now(),
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )
        create_interactive_audit_chunk(
            str(session.id),
            InteractiveRunAuditDirection.OUTPUT,
            'postgres=# SELECT 1;\n',
        )

        response = self.client.get(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/{session.id}/terminal_events/'
        )

        self.assertEqual(response.status_code, 200)
        streamed_content = b''.join(
            chunk if isinstance(chunk, bytes) else chunk.encode('utf-8')
            for chunk in response.streaming_content
        ).decode('utf-8')
        self.assertIn('event: output', streamed_content)
        self.assertIn('postgres=# SELECT 1;', streamed_content)
        self.assertFalse(session.events.filter(event_type=InteractiveRunEventType.OUTPUT).exists())


class InteractiveRunRunnerClaimTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='runner-claim@example.com',
            password='senha123',
            name='Runner Claim User',
        )
        self.project = Project.objects.create(name='Projeto Runner Claim')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-runner-claim',
            name_dokku='app-runner-claim',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )

    def test_claim_pending_sessions_marks_runner_without_starting_execution(self):
        InteractiveRunRunner.objects.create(
            runner_id='runner-claim-test',
            hostname='test-host',
            pid=321,
            max_sessions=2,
            active_sessions=0,
            last_heartbeat_at=timezone.now(),
        )
        session = InteractiveRunSession.objects.create(
            app=self.app,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
            status=InteractiveRunSessionStatus.PENDING,
            manage_path='manage.py',
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )

        claimed = claim_pending_interactive_sessions('runner-claim-test', limit=1)

        self.assertEqual([str(item.id) for item in claimed], [str(session.id)])
        session.refresh_from_db()
        self.assertEqual(session.runner_id, 'runner-claim-test')
        self.assertIsNotNone(session.claimed_at)
        self.assertEqual(session.status, InteractiveRunSessionStatus.PENDING)

    def test_has_live_runner_ignores_stale_heartbeat(self):
        InteractiveRunRunner.objects.create(
            runner_id='runner-stale-test',
            hostname='test-host',
            pid=321,
            max_sessions=2,
            active_sessions=0,
            last_heartbeat_at=timezone.now() - timedelta(minutes=10),
        )

        self.assertFalse(has_live_interactive_runner())


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class InteractiveRunWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user(
            email='interactive-ws@example.com',
            password='senha123',
            name='Interactive WS User',
        )
        self.other_user = User.objects.create_user(
            email='interactive-ws-other@example.com',
            password='senha123',
            name='Interactive WS Other User',
        )
        self.token = CLIToken.objects.create(user=self.user)
        self.other_token = CLIToken.objects.create(user=self.other_user)
        self.project = Project.objects.create(name='Projeto Interactive WS')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-interactive-ws',
            name_dokku='app-interactive-ws',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )
        self.session = InteractiveRunSession.objects.create(
            app=self.app,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
            status=InteractiveRunSessionStatus.AWAITING_INPUT,
            manage_path='manage.py',
            awaiting_prompt_id='email-1',
            awaiting_prompt_text='Email address:',
            awaiting_prompt_secret=False,
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )

    def _communicator(self, token=None, session=None):
        session = session or self.session
        headers = []
        if token:
            headers.append((b'authorization', f'CLI {token.token}'.encode('utf-8')))
        return WebsocketCommunicator(
            application,
            f'/ws/apps/apps/{self.app.id}/interactive_sessions/{session.id}/',
            headers=headers,
        )

    def test_websocket_rejects_missing_cli_token(self):
        async def scenario():
            communicator = self._communicator()
            connected, _subprotocol = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(scenario)()

    def test_websocket_rejects_session_from_other_user(self):
        async def scenario():
            communicator = self._communicator(token=self.other_token)
            connected, _subprotocol = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(scenario)()

    def test_websocket_accepts_answer_and_keeps_plaintext_out_of_database(self):
        async def scenario():
            communicator = self._communicator(token=self.token)
            connected, _subprotocol = await communicator.connect()
            self.assertTrue(connected)
            connected_message = await communicator.receive_json_from()
            self.assertEqual(connected_message['type'], 'status')

            await communicator.send_json_to({
                'type': 'answer',
                'prompt_id': 'email-1',
                'value': 'admin@example.com',
            })
            ack = await communicator.receive_json_from()
            self.assertEqual(ack['type'], 'ack')
            await communicator.disconnect()

        async_to_sync(scenario)()
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.pending_answer_ciphertext)
        self.assertNotIn(b'admin@example.com', bytes(self.session.pending_answer_ciphertext))


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class InteractiveRunTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='interactive-task@example.com',
            password='senha123',
            name='Interactive Task User',
        )
        self.project = Project.objects.create(name='Projeto Interactive Task')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-interactive-task',
            name_dokku='app-interactive-task',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )

    def _make_session(self):
        return InteractiveRunSession.objects.create(
            app=self.app,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
            status=InteractiveRunSessionStatus.PENDING,
            manage_path='manage.py',
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )

    def _run_task_with_script(self, scripted_outputs, answers):
        session = self._make_session()
        channel = FakeInteractiveChannel(scripted_outputs)

        original_set_prompt = interactive_run._set_session_prompt
        answers_iter = iter(answers)

        def auto_answer(session_id, prompt_match):
            prompt_id = original_set_prompt(session_id, prompt_match)
            submit_interactive_session_answer(session_id, prompt_id, next(answers_iter))
            return prompt_id

        task = AppMixin.run_interactive_session
        with (
            patch('core.apps.mixins.apps.interactive_run.DokkuAdapter') as mock_dokku_cls,
            patch('core.apps.mixins.apps.interactive_run._set_session_prompt', side_effect=auto_answer),
            patch('core.apps.mixins.apps.interactive_run.time.sleep', return_value=None),
        ):
            mock_dokku_cls.return_value.open_interactive_channel.return_value = channel
            task.request.id = 'task-interactive-session'
            result = task.run(session_id=str(session.id))

        session.refresh_from_db()
        return result, session, channel

    def test_run_interactive_session_completes_createsuperuser_flow(self):
        result, session, channel = self._run_task_with_script(
            [
                'Email address: ',
                'Name: ',
                'Password: ',
                'Password (again): ',
                'Superuser created successfully.\n',
            ],
            ['admin@example.com', 'Admin', '123123Admin', '123123Admin'],
        )

        self.assertEqual(result['status'], 'success')
        self.assertEqual(session.status, InteractiveRunSessionStatus.COMPLETED)
        self.assertEqual(channel.written_inputs, ['admin@example.com', 'Admin', '123123Admin', '123123Admin'])
        self.assertEqual(session.events.filter(event_type=InteractiveRunEventType.PROMPT).count(), 4)
        self.assertTrue(session.events.filter(event_type=InteractiveRunEventType.COMPLETE).exists())
        self.assertFalse(any('123123Admin' in str(event.payload) for event in session.events.all()))

    def test_run_interactive_session_uses_postgres_connect_and_audits_output(self):
        service = Service.objects.create(
            name='db-task-terminal',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=self.app,
            project=self.project,
            service_type='postgres',
            container_name='db-task-terminal',
        )
        session = InteractiveRunSession.objects.create(
            app=self.app,
            service=service,
            created_by=self.user,
            command_kind=InteractiveRunCommandKind.POSTGRES_CONNECT,
            status=InteractiveRunSessionStatus.PENDING,
            manage_path='manage.py',
            expires_at=timezone.now() + timedelta(minutes=5),
            last_activity_at=timezone.now(),
        )
        channel = FakeInteractiveChannel(['postgres=# '])

        task = AppMixin.run_interactive_session
        with (
            patch('core.apps.mixins.apps.interactive_run.DokkuAdapter') as mock_dokku_cls,
            patch('core.apps.mixins.apps.interactive_run.time.sleep', return_value=None),
        ):
            mock_dokku_cls.return_value.open_interactive_channel.return_value = channel
            task.request.id = 'task-postgres-connect-session'
            result = task.run(session_id=str(session.id))

        session.refresh_from_db()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(session.status, InteractiveRunSessionStatus.COMPLETED)
        mock_dokku_cls.return_value.open_interactive_channel.assert_called_once_with('postgres:connect db-task-terminal')
        chunk = session.audit_chunks.get(direction=InteractiveRunAuditDirection.OUTPUT)
        self.assertEqual(decrypt_interactive_text(chunk.content_ciphertext), 'postgres=# ')
        self.assertFalse(session.events.filter(event_type=InteractiveRunEventType.OUTPUT).exists())

    def test_run_interactive_session_suppresses_echoes_and_redacts_sensitive_output(self):
        result, session, channel = self._run_task_with_script(
            [
                'Email address: ',
                'admin@example.com\nName: ',
                'Admin\nPassword: ',
                'pass: 123123Admin and userrrr: admin@example.com\nPassword (again): ',
                'Superuser created successfully.\n',
            ],
            ['admin@example.com', 'Admin', '123123Admin', '123123Admin'],
        )

        self.assertEqual(result['status'], 'success')
        self.assertEqual(channel.written_inputs, ['admin@example.com', 'Admin', '123123Admin', '123123Admin'])

        output_messages = [
            event.payload['message']
            for event in session.events.filter(event_type=InteractiveRunEventType.OUTPUT).order_by('id')
        ]
        self.assertNotIn('admin@example.com', output_messages)
        self.assertNotIn('Admin', output_messages)
        self.assertIn('[conteudo sensivel ocultado]', output_messages)
        self.assertFalse(any('123123Admin' in message for message in output_messages))

        complete_event = session.events.get(event_type=InteractiveRunEventType.COMPLETE)
        self.assertTrue(complete_event.payload['silent'])

    def test_run_interactive_session_handles_validation_message_and_reprompt(self):
        result, session, channel = self._run_task_with_script(
            [
                'Email address: ',
                'Error: That email address is already taken.\nEmail address: ',
                'Name: ',
                'Password: ',
                'Password (again): ',
                'Superuser created successfully.\n',
            ],
            ['used@example.com', 'admin@example.com', 'Admin', '123123Admin', '123123Admin'],
        )

        self.assertEqual(result['status'], 'success')
        self.assertEqual(session.status, InteractiveRunSessionStatus.COMPLETED)
        self.assertEqual(channel.written_inputs[0], 'used@example.com')
        self.assertEqual(channel.written_inputs[1], 'admin@example.com')
        self.assertTrue(any('already taken' in str(event.payload) for event in session.events.all()))


class DokkuConfigMixinTests(SimpleTestCase):
    def test_set_config_supports_no_restart_flag(self):
        adapter = FakeConfigAdapter()

        output = adapter.set_config(app_name='my-app', env_vars={'SECRET_KEY': 'abc'}, no_restart=True)

        self.assertEqual(output, 'OK')
        self.assertEqual(adapter.commands, ['config:set --no-restart my-app SECRET_KEY=abc'])

    def test_set_config_batches_multiple_variables_into_one_command(self):
        adapter = FakeConfigAdapter()

        adapter.set_config(app_name='my-app', env_vars={'SECRET_KEY': 'abc', 'DEBUG': 'false'}, no_restart=True)

        self.assertEqual(len(adapter.commands), 1)
        self.assertEqual(adapter.commands[0], 'config:set --no-restart my-app SECRET_KEY=abc DEBUG=false')

    def test_unset_config_batches_keys_with_no_restart(self):
        adapter = FakeConfigAdapter()

        output = adapter.unset_config(app_name='my-app', keys=['OLD_KEY', 'DEBUG'], no_restart=True)

        self.assertEqual(output, 'OK')
        self.assertEqual(adapter.commands, ['config:unset --no-restart my-app OLD_KEY DEBUG'])

    def test_set_config_quotes_values_with_spaces(self):
        adapter = FakeConfigAdapter()

        adapter.set_config(app_name='my-app', env_vars={'DISPLAY_NAME': 'Meu App'}, no_restart=True)

        self.assertEqual(adapter.commands, ["config:set --no-restart my-app 'DISPLAY_NAME=Meu App'"])


class DokkuGitMixinTests(SimpleTestCase):
    def test_sync_git_streaming_treats_fatal_auth_prompt_as_failure(self):
        adapter = FakeGitAdapter([
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
        ])

        output = adapter.sync_git_streaming(
            app_name='my-app',
            git_url='https://github.com/org/private-repo.git',
            branch='main',
        )

        self.assertEqual(output, 'Failed to sync Git repository and deploy.')


class LogRedactionTests(SimpleTestCase):
    def test_redacts_sensitive_config_values_from_dokku_output(self):
        message = '\n'.join([
            '-----> Setting config vars',
            'DEBUG: True',
            'SECRET_KEY: abc123',
            'DATABASE_URL: postgres://user:pass@host/db',
            'TOKEN=value',
        ])

        redacted = redact_sensitive_log_message(message)

        self.assertIn('DEBUG: True', redacted)
        self.assertIn('SECRET_KEY: [oculto]', redacted)
        self.assertIn('DATABASE_URL: [oculto]', redacted)
        self.assertIn('TOKEN=[oculto]', redacted)
        self.assertNotIn('abc123', redacted)
        self.assertNotIn('postgres://user:pass@host/db', redacted)


class DokkuAppsMixinTests(SimpleTestCase):
    def test_exists_app_raises_when_apps_list_fails(self):
        adapter = FakeAppsAdapter('SSH Command Timeout after 120s while executing: apps:list')

        with self.assertRaises(RuntimeError):
            adapter.exists_app('my-app')


class SSHAdapterTests(SimpleTestCase):
    @patch('infrastructure.adapters.ssh.paramiko.SSHClient')
    def test_run_command_applies_connect_and_channel_timeouts(self, mock_ssh_client_cls):
        client = Mock()
        stdout = Mock()
        stderr = Mock()
        stdin = Mock()
        stdout.read.return_value = b'OK'
        stderr.read.return_value = b''
        stdout.channel.recv_exit_status.return_value = 0
        client.exec_command.return_value = (stdin, stdout, stderr)
        mock_ssh_client_cls.return_value = client

        adapter = SSHAdapter('dokku.example.com', 'dokku', 'fake-key', 22, connect_timeout=12, command_timeout=34)

        with patch.object(adapter, '_get_pkey', return_value=Mock()):
            output = adapter._run_command('apps:list')

        self.assertEqual(output, 'OK')
        client.connect.assert_called_once_with(
            'dokku.example.com',
            port=22,
            username='dokku',
            pkey=ANY,
            timeout=12,
            banner_timeout=12,
            auth_timeout=12,
        )
        stdout.channel.settimeout.assert_called_once_with(34)
        stderr.channel.settimeout.assert_called_once_with(34)

    @patch('infrastructure.adapters.ssh.paramiko.SSHClient')
    def test_run_command_returns_timeout_message(self, mock_ssh_client_cls):
        client = Mock()
        stdout = Mock()
        stderr = Mock()
        stdin = Mock()
        stdout.read.side_effect = socket.timeout('timed out')
        client.exec_command.return_value = (stdin, stdout, stderr)
        mock_ssh_client_cls.return_value = client

        adapter = SSHAdapter('dokku.example.com', 'dokku', 'fake-key', 22, command_timeout=45)

        with patch.object(adapter, '_get_pkey', return_value=Mock()):
            output = adapter._run_command('apps:list')

        self.assertEqual(output, 'SSH Command Timeout after 45s while executing: apps:list')


class StorageUsageTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = User.objects.create_user(
            email='superuser-storage@example.com',
            password='senha123',
            name='Superuser Storage',
            is_superuser=True,
            is_staff=True,
        )
        self.client.force_authenticate(user=self.superuser)
        cache.clear()

    @patch('core.apps.admin_views.DokkuAdapter')
    def test_storage_usage_avoids_n_plus_one_when_resolving_apps(self, mock_dokku_cls):
        mock_dokku = Mock()
        mock_dokku.get_database_size.return_value = 1024
        mock_dokku.app_links_for_service.side_effect = (
            lambda container_name: container_name.replace('db-', 'app-')
        )
        mock_dokku_cls.return_value = mock_dokku

        for index in range(5):
            owner = User.objects.create_user(
                email=f'owner-storage-{index}@example.com',
                password='senha123',
                name=f'Owner Storage {index}',
            )
            project = Project.objects.create(name=f'Projeto Storage {index}')
            project.users.add(owner)
            App.objects.create(
                name=f'app-storage-{index}',
                name_dokku=f'app-storage-{index}',
                git='https://github.com/org/repo.git',
                branch='main',
                project=project,
                status='RUNNING',
            )
            Service.objects.create(
                name=f'db-storage-{index}',
                user='postgres',
                password='secret',
                host='localhost',
                port=5432,
                app=None,
                project=project,
                service_type='postgres',
                container_name=f'db-storage-{index}',
            )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/admin-api/storage-usage/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['services']), 5)
        self.assertTrue(all(service['app_name'].startswith('app-storage-') for service in response.data['services']))
        self.assertLessEqual(len(queries), 4)

    @patch('core.apps.admin_views.DokkuAdapter')
    def test_storage_usage_uses_cache_until_force_refresh(self, mock_dokku_cls):
        mock_dokku = Mock()
        mock_dokku.get_database_size.return_value = 2048
        mock_dokku.app_links_for_service.return_value = 'app-storage-cache'
        mock_dokku_cls.return_value = mock_dokku

        owner = User.objects.create_user(
            email='owner-storage-cache@example.com',
            password='senha123',
            name='Owner Storage Cache',
        )
        project = Project.objects.create(name='Projeto Storage Cache')
        project.users.add(owner)
        App.objects.create(
            name='app-storage-cache',
            name_dokku='app-storage-cache',
            git='https://github.com/org/repo.git',
            branch='main',
            project=project,
            status='RUNNING',
        )
        Service.objects.create(
            name='db-storage-cache',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=None,
            project=project,
            service_type='postgres',
            container_name='db-storage-cache',
        )

        first_response = self.client.get('/api/admin-api/storage-usage/')
        second_response = self.client.get('/api/admin-api/storage-usage/')
        refreshed_response = self.client.get('/api/admin-api/storage-usage/?refresh=1')

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(refreshed_response.status_code, 200)
        self.assertEqual(mock_dokku_cls.call_count, 2)

    @patch('core.apps.admin_views.DokkuAdapter')
    def test_storage_usage_cache_is_invalidated_when_services_change(self, mock_dokku_cls):
        mock_dokku = Mock()
        mock_dokku.get_database_size.return_value = 4096
        mock_dokku.app_links_for_service.side_effect = (
            lambda container_name: container_name.replace('db-', 'app-')
        )
        mock_dokku_cls.return_value = mock_dokku

        owner = User.objects.create_user(
            email='owner-storage-invalid@example.com',
            password='senha123',
            name='Owner Storage Invalid',
        )
        project = Project.objects.create(name='Projeto Storage Invalid')
        project.users.add(owner)
        App.objects.create(
            name='app-storage-invalid',
            name_dokku='app-storage-invalid',
            git='https://github.com/org/repo.git',
            branch='main',
            project=project,
            status='RUNNING',
        )
        Service.objects.create(
            name='db-storage-invalid',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=None,
            project=project,
            service_type='postgres',
            container_name='db-storage-invalid',
        )

        first_response = self.client.get('/api/admin-api/storage-usage/')

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(len(first_response.data['services']), 1)

        Service.objects.create(
            name='db-storage-invalid-2',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=None,
            project=project,
            service_type='postgres',
            container_name='db-storage-invalid-2',
        )

        refreshed_response = self.client.get('/api/admin-api/storage-usage/')

        self.assertEqual(refreshed_response.status_code, 200)
        self.assertEqual(len(refreshed_response.data['services']), 2)
