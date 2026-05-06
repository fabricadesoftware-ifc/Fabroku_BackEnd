import socket
from datetime import timedelta
from unittest.mock import ANY, Mock, patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from core.adapters.dokku_mixins.dokku_apps import DokkuAppsMixin
from core.adapters.dokku_mixins.dokku_config import DokkuConfigMixin
from core.adapters.ssh import SSHAdapter
from core.cache_versioning import APP_LAST_COMMIT_CACHE_NAMESPACE, get_cache_ttl
from core.apps.mixins import AppMixin
from core.apps.mixins.apps import interactive_run
from core.apps.mixins.apps.interactive_run import get_interactive_driver, submit_interactive_session_answer
from core.apps.mixins.apps.run_data import validate_dump_args, validate_manage_path
from core.apps.mixins.apps.create_app import CreateAppMixin
from core.apps.mixins.apps.redeploy_app import RedeployAppMixin
from core.apps.models import (
    App,
    AppRunArtifact,
    AppRunArtifactKind,
    InteractiveRunCommandKind,
    InteractiveRunEvent,
    InteractiveRunEventType,
    InteractiveRunSession,
    InteractiveRunSessionStatus,
    Service,
)
from core.auth_user.models import User
from core.project.models import Project


class FakeStatus:
    def __init__(self, state='success', description='ok', created_at='2026-04-16T00:00:00Z', context='fabroku/deploy'):
        self.state = state
        self.description = description
        self.created_at = created_at
        self.context = context


class FakeCommit:
    def __init__(self, sha='abc123def456'):
        self.sha = sha

    def get_statuses(self):
        return [FakeStatus()]


class FakeBranch:
    def __init__(self, sha='abc123def456'):
        self.commit = FakeCommit(sha=sha)


class FakeHook:
    def __init__(self, hook_id, url, active=True):
        self.id = hook_id
        self.active = active
        self.config = {'url': url}


class FakeRepo:
    def __init__(self, expected_url):
        self.expected_url = expected_url

    def get_hooks(self):
        return [FakeHook(77, self.expected_url)]

    def get_branch(self, branch_name):
        return FakeBranch()


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


class FakeRedeployDokkuAdapter:
    def __init__(
        self,
        *,
        set_config_output: str = 'OK',
        app_list_output: str = 'app-redeploy-teste',
        start_database_output: str = 'service started',
    ):
        self.set_config_output = set_config_output
        self.app_list_output = app_list_output
        self.start_database_output = start_database_output
        self.set_config_calls = []
        self.start_database_calls = []

    def start_database(self, db_name: str) -> str:
        self.start_database_calls.append(db_name)
        return self.start_database_output

    def get_apps(self) -> str:
        return self.app_list_output

    def exists_app(self, app_name: str) -> bool:
        return True

    def set_config(self, **kwargs):
        self.set_config_calls.append(kwargs)
        return self.set_config_output

    def sync_git_streaming(self, **kwargs):
        return 'Sync complete'

    def get_app_domain(self, app_name: str) -> str:
        return 'app.example.com'

    def enable_letsencrypt(self, app_name: str) -> str:
        return 'OK'


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
        for value in ('/app/manage.py', '../manage.py', 'src/settings.py', 'C:/app/manage.py'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_manage_path(value)

    def test_validate_dump_args_blocks_output_and_shell_operators(self):
        for args in (['--output', 'dump.json'], ['--output=dump.json'], ['auth.User', '&&', 'rm']):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    validate_dump_args(args)


class InteractiveRunValidationTests(SimpleTestCase):
    def test_createsuperuser_driver_matches_expected_prompts(self):
        driver = get_interactive_driver(InteractiveRunCommandKind.DJANGO_CREATESUPERUSER)

        samples = [
            ('Email address: ', 'email', False),
            ('Name: ', 'name', False),
            ('Password: ', 'password', True),
            ('Password (again): ', 'password_confirmation', True),
        ]

        for prompt_text, prompt_key, is_secret in samples:
            with self.subTest(prompt_text=prompt_text):
                prompt_match = driver.match_prompt(prompt_text)
                self.assertIsNotNone(prompt_match)
                self.assertEqual(prompt_match.spec.key, prompt_key)
                self.assertEqual(prompt_match.spec.secret, is_secret)


class FakeInteractiveChannel:
    def __init__(self, scripted_outputs, exit_status=0):
        self.pending_outputs = [scripted_outputs[0]] if scripted_outputs else []
        self.future_outputs = list(scripted_outputs[1:])
        self.exit_status = exit_status
        self.written_inputs = []
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def recv_ready(self):
        return bool(self.pending_outputs)

    def recv(self, size):
        if not self.pending_outputs:
            return b''
        return self.pending_outputs.pop(0).encode('utf-8')

    def recv_stderr_ready(self):
        return False

    def recv_stderr(self, size):
        return b''

    def exit_status_ready(self):
        return not self.pending_outputs and not self.future_outputs

    def recv_exit_status(self):
        return self.exit_status

    def handle_input(self, value):
        self.written_inputs.append(value.rstrip('\n'))
        if self.future_outputs:
            self.pending_outputs.append(self.future_outputs.pop(0))


class FakeInteractiveStdin:
    def __init__(self, channel):
        self.channel = channel

    def write(self, value):
        self.channel.handle_input(value)

    def flush(self):
        return None

    def close(self):
        return None


class FakeInteractiveStdStream:
    def __init__(self, channel):
        self.channel = channel


class FakeInteractiveClient:
    def close(self):
        return None


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
        self.client.force_authenticate(user=self.user)

    @patch('core.apps.views.AppMixin.run_interactive_session.delay')
    def test_create_interactive_session_dispatches_task(self, mock_delay):
        mock_delay.return_value = Mock(id='task-interactive-123')

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/interactive_sessions/',
            {'command_kind': 'django_createsuperuser', 'manage_path': 'src/manage.py'},
            format='json',
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['task_id'], 'task-interactive-123')
        session = InteractiveRunSession.objects.get(id=response.data['session_id'])
        self.assertEqual(session.status, InteractiveRunSessionStatus.PENDING)
        self.assertEqual(session.manage_path, 'src/manage.py')
        self.assertEqual(session.task_id, 'task-interactive-123')
        mock_delay.assert_called_once_with(session_id=str(session.id))

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
        stdin = FakeInteractiveStdin(channel)
        stdout = FakeInteractiveStdStream(channel)
        stderr = FakeInteractiveStdStream(channel)

        original_set_prompt = interactive_run._set_session_prompt
        answers_iter = iter(answers)

        def auto_answer(session_id, prompt_match):
            prompt_id = original_set_prompt(session_id, prompt_match)
            submit_interactive_session_answer(session_id, prompt_id, next(answers_iter))
            return prompt_id

        task = AppMixin.run_interactive_session
        with (
            patch('core.apps.mixins.apps.interactive_run._open_interactive_command', return_value=(FakeInteractiveClient(), stdin, stdout, stderr)),
            patch('core.apps.mixins.apps.interactive_run._set_session_prompt', side_effect=auto_answer),
            patch('core.apps.mixins.apps.interactive_run.time.sleep', return_value=None),
        ):
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


class DokkuAppsMixinTests(SimpleTestCase):
    def test_exists_app_raises_when_apps_list_fails(self):
        adapter = FakeAppsAdapter('SSH Command Timeout after 120s while executing: apps:list')

        with self.assertRaises(RuntimeError):
            adapter.exists_app('my-app')


class SSHAdapterTests(SimpleTestCase):
    @patch('core.adapters.ssh.paramiko.SSHClient')
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

    @patch('core.adapters.ssh.paramiko.SSHClient')
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


class EnvVarFlowTests(TestCase):
    def test_create_app_apply_env_vars_uses_no_restart(self):
        task = Mock()
        adapter = Mock()
        logger = Mock()
        env_vars = {'SECRET_KEY': 'abc', 'DEBUG': 'false'}
        adapter.set_config.return_value = 'OK'

        CreateAppMixin._apply_env_vars(task, adapter, 'my-app', env_vars, logger)

        adapter.set_config.assert_called_once_with(app_name='my-app', env_vars=env_vars, no_restart=True)
        self.assertIn('--no-restart', logger.dokku.call_args.kwargs['command'])

    @patch('core.apps.mixins.apps.redeploy_app.AppLogManager')
    @patch('core.apps.mixins.apps.redeploy_app.DokkuAdapter')
    @patch('core.apps.mixins.apps.redeploy_app.RedeployAppMixin._get_git_token', return_value=None)
    def test_redeploy_syncs_env_vars_without_restart_and_logs_preflight(
        self, mock_get_git_token, mock_dokku_cls, mock_logger_cls,
    ):
        user = User.objects.create_user(email='redeploy@example.com', password='senha123', name='Redeploy User')
        project = Project.objects.create(name='Projeto Redeploy')
        project.users.add(user)
        app = App.objects.create(
            name='app-redeploy-teste',
            name_dokku='app-redeploy-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=project,
            variables={'SECRET_KEY': 'abc'},
            domain='app.example.com',
        )
        Service.objects.create(
            name='db-redeploy-teste',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=app,
            project=project,
            service_type='postgres',
            container_name='db-redeploy-teste',
        )

        fake_dokku = FakeRedeployDokkuAdapter()
        mock_dokku_cls.return_value = fake_dokku
        mock_logger = Mock()
        mock_logger_cls.return_value = mock_logger
        task = RedeployAppMixin.redeploy_app

        with patch.object(task, 'update_state') as mock_update_state:
            task.request.id = 'task-123'
            result = task.run(app_id=app.id, commit=None)

        self.assertEqual(result['status'], 'success')
        self.assertTrue(mock_update_state.called)
        self.assertEqual(fake_dokku.start_database_calls, ['db-redeploy-teste'])
        self.assertEqual(fake_dokku.set_config_calls, [
            {
                'app_name': 'app-redeploy-teste',
                'env_vars': {'SECRET_KEY': 'abc'},
                'no_restart': True,
            }
        ])
        commands = [call.kwargs.get('command', '') for call in mock_logger.dokku.call_args_list]
        self.assertIn('dokku postgres:start db-redeploy-teste', commands)
        self.assertIn('dokku apps:list', commands)
        self.assertIn('dokku config:set --no-restart app-redeploy-teste [vars: SECRET_KEY]', commands)

    @patch('core.apps.mixins.apps.redeploy_app.AppLogManager')
    @patch('core.apps.mixins.apps.redeploy_app.DokkuAdapter')
    @patch('core.apps.mixins.apps.redeploy_app.RedeployAppMixin._get_git_token', return_value=None)
    def test_redeploy_fails_fast_when_config_step_times_out(self, mock_get_git_token, mock_dokku_cls, mock_logger_cls):
        user = User.objects.create_user(email='redeploy-timeout@example.com', password='senha123', name='Timeout User')
        project = Project.objects.create(name='Projeto Timeout')
        project.users.add(user)
        app = App.objects.create(
            name='app-timeout-teste',
            name_dokku='app-timeout-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=project,
            variables={'SECRET_KEY': 'abc'},
        )

        fake_dokku = FakeRedeployDokkuAdapter(
            set_config_output='SSH Command Timeout after 120s while executing: config:set app-timeout-teste SECRET_KEY=abc'
        )
        mock_dokku_cls.return_value = fake_dokku
        mock_logger_cls.return_value = Mock()
        task = RedeployAppMixin.redeploy_app

        with patch.object(task, 'update_state'):
            task.request.id = 'task-timeout-123'
            with self.assertRaises(RuntimeError):
                task.run(app_id=app.id, commit=None)

        app.refresh_from_db()
        self.assertEqual(app.status, 'ERROR')


class LinkServiceMixinTests(TestCase):
    @patch('core.apps.mixins.services.link_service.DokkuAdapter')
    def test_link_service_allows_unlinked_service_without_none_id_error(self, mock_dokku_cls):
        user = User.objects.create_user(email='link@example.com', password='senha123', name='Link User')
        project = Project.objects.create(name='Projeto Link')
        project.users.add(user)
        app = App.objects.create(
            name='app-link-teste',
            name_dokku='app-link-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=project,
            variables={},
        )
        service = Service.objects.create(
            name='db-link-teste',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=None,
            project=project,
            service_type='postgres',
            container_name='db-link-teste',
        )

        mock_dokku = Mock()
        mock_dokku.link_database.return_value = 'already linked'
        mock_dokku.get_config.return_value = 'postgres://db-link-teste'
        mock_dokku.start_database.return_value = 'OK'
        mock_dokku.restart_app.return_value = 'restart ok'
        mock_dokku_cls.return_value = mock_dokku

        task = AppMixin.link_service
        with patch.object(task, 'update_state'):
            task.request.id = 'task-link-123'
            result = task.run(service_id=service.id, app_id=app.id)

        self.assertEqual(result['status'], 'linked')
        service.refresh_from_db()
        app.refresh_from_db()
        self.assertEqual(service.app_id, app.id)
        self.assertEqual(app.variables['DATABASE_URL'], 'postgres://db-link-teste')
        self.assertEqual(app.task_id, 'task-link-123')
        mock_dokku.restart_app.assert_called_once_with(app.name_dokku)


class RunCommandTests(TestCase):
    @patch('core.apps.mixins.apps.run_command.DokkuAdapter')
    def test_run_command_marks_task_as_failure_when_output_contains_traceback(self, mock_dokku_cls):
        user = User.objects.create_user(email='command@example.com', password='senha123', name='Command User')
        project = Project.objects.create(name='Projeto Command')
        project.users.add(user)
        app = App.objects.create(
            name='app-command-teste',
            name_dokku='app-command-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=project,
            variables={},
        )

        mock_dokku = Mock()
        mock_dokku.run_in_app_streaming.return_value = iter([
            'Traceback (most recent call last):',
            'django.db.utils.ProgrammingError: relation "foo" does not exist',
        ])
        mock_dokku_cls.return_value = mock_dokku

        task = AppMixin.run_command
        with patch.object(task, 'update_state'):
            task.request.id = 'task-command-123'
            with self.assertRaises(RuntimeError):
                task.run(app_id=app.id, command='python manage.py migrate')

        app.refresh_from_db()
        self.assertEqual(app.error_type, 'CommandExecutionError')
        self.assertIn('ProgrammingError', app.error_details)


class ManageAppEndpointTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='manage@example.com',
            password='senha123',
            name='Manage User',
        )
        self.project = Project.objects.create(name='Projeto Manage')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-manage-teste',
            name_dokku='app-manage-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )
        self.client.force_authenticate(user=self.user)

    @patch('core.apps.views.AppMixin.manage_app_task.delay')
    def test_stop_endpoint_dispatches_manage_app_task(self, mock_delay):
        mock_delay.return_value = Mock(id='task-stop-123')

        response = self.client.post(f'/api/apps/apps/{self.app.id}/stop/')

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['status'], 'STOPPING')
        self.assertEqual(response.data['task_id'], 'task-stop-123')
        mock_delay.assert_called_once_with(app_id=self.app.id, action='stop')

    @patch('core.apps.views.AppLogManager')
    @patch('core.apps.views.AppMixin.manage_app_task.delay')
    @patch('core.apps.views.AsyncResult')
    def test_stop_endpoint_cancels_redeploy_instead_of_stopping_app(
        self, mock_async_result_cls, mock_delay, mock_logger_cls,
    ):
        self.app.status = 'DEPLOYING'
        self.app.task_id = 'task-redeploy-123'
        self.app.save(update_fields=['status', 'task_id'])

        mock_async_result = Mock()
        mock_async_result.state = 'PROGRESS'
        mock_async_result_cls.return_value = mock_async_result

        response = self.client.post(f'/api/apps/apps/{self.app.id}/stop/')

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['status'], 'RUNNING')
        self.assertEqual(response.data['task_id'], 'task-redeploy-123')
        self.assertEqual(response.data['cancelled_task_id'], 'task-redeploy-123')
        mock_async_result.revoke.assert_called_once_with(terminate=True, signal='SIGTERM')
        mock_delay.assert_not_called()
        mock_logger_cls.return_value.warning.assert_called_once()

        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'RUNNING')

    @patch('core.apps.views.AsyncResult')
    def test_get_app_status_returns_cancelled_message_for_revoked_task(self, mock_async_result_cls):
        self.app.task_id = 'task-redeploy-123'
        self.app.save(update_fields=['task_id'])

        mock_async_result = Mock()
        mock_async_result.state = 'REVOKED'
        mock_async_result_cls.return_value = mock_async_result

        response = self.client.get(f'/api/apps/apps/{self.app.id}/get_app_status/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['state'], 'REVOKED')
        self.assertEqual(response.data['status'], 'OperaÃ§Ã£o cancelada pelo usuÃ¡rio.')
        self.assertEqual(response.data['current'], 100)


class RunCommandStatusEndpointTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='status@example.com',
            password='senha123',
            name='Status User',
        )
        self.project = Project.objects.create(name='Projeto Status')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-status-teste',
            name_dokku='app-status-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
            task_id='task-command-success',
        )
        self.client.force_authenticate(user=self.user)

    @patch('core.apps.views.AsyncResult')
    def test_get_app_status_returns_command_output_on_success(self, mock_async_result_cls):
        mock_async_result = Mock()
        mock_async_result.state = 'SUCCESS'
        mock_async_result.result = {
            'status': 'success',
            'message': 'Comando executado com sucesso: python manage.py migrate',
            'command': 'python manage.py migrate',
            'output': 'No migrations to apply.',
            'lines': 1,
        }
        mock_async_result_cls.return_value = mock_async_result

        response = self.client.get(f'/api/apps/apps/{self.app.id}/get_app_status/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['state'], 'SUCCESS')
        self.assertEqual(response.data['status'], 'Comando executado com sucesso: python manage.py migrate')
        self.assertEqual(response.data['command'], 'python manage.py migrate')
        self.assertEqual(response.data['output'], 'No migrations to apply.')
        self.assertEqual(response.data['lines'], 1)
        self.assertEqual(response.data['current'], 100)


class RunDataEndpointTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='run-data@example.com',
            password='senha123',
            name='Run Data User',
        )
        self.project = Project.objects.create(name='Projeto Run Data')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-run-data',
            name_dokku='app-run-data',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )
        self.client.force_authenticate(user=self.user)

    @patch('core.apps.views.AppMixin.run_loaddata.delay')
    def test_run_loaddata_creates_upload_artifact_and_dispatches_task(self, mock_delay):
        mock_delay.return_value = Mock(id='task-loaddata-123')
        fixture = SimpleUploadedFile(
            'my_data.json',
            b'[{"model":"auth.user","fields":{"username":"alice"}}]',
            content_type='application/json',
        )

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/run_loaddata/',
            {'fixture': fixture, 'manage_path': 'src/manage.py'},
            format='multipart',
        )

        self.assertEqual(response.status_code, 202)
        artifact = AppRunArtifact.objects.get(app=self.app, kind=AppRunArtifactKind.LOAD_DATA_UPLOAD)
        self.assertEqual(artifact.filename, 'my_data.json')
        self.assertEqual(bytes(artifact.content), b'[{"model":"auth.user","fields":{"username":"alice"}}]')
        mock_delay.assert_called_once_with(
            app_id=self.app.id,
            artifact_id=str(artifact.id),
            manage_path='src/manage.py',
            user_id=self.user.id,
        )

    def test_run_loaddata_rejects_unsafe_manage_path(self):
        fixture = SimpleUploadedFile('my_data.json', b'[]', content_type='application/json')

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/run_loaddata/',
            {'fixture': fixture, 'manage_path': '../manage.py'},
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AppRunArtifact.objects.count(), 0)

    def test_run_dumpdata_rejects_dangerous_args(self):
        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/run_dumpdata/',
            {
                'manage_path': 'manage.py',
                'dump_args': ['--output', 'dump.json'],
                'output_filename': 'dump.json',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    @patch('core.apps.views.AppMixin.run_dumpdata.delay')
    def test_run_dumpdata_dispatches_task(self, mock_delay):
        mock_delay.return_value = Mock(id='task-dumpdata-123')

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/run_dumpdata/',
            {
                'manage_path': 'src/manage.py',
                'dump_args': ['--indent', '2', 'auth.User'],
                'output_filename': 'users.json',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 202)
        mock_delay.assert_called_once_with(
            app_id=self.app.id,
            manage_path='src/manage.py',
            dump_args=['--indent', '2', 'auth.User'],
            output_filename='users.json',
            user_id=self.user.id,
        )

    def test_download_artifact_requires_project_access(self):
        other_user = User.objects.create_user(
            email='other-run-data@example.com',
            password='senha123',
            name='Other Run Data',
        )
        artifact = AppRunArtifact.objects.create(
            app=self.app,
            created_by=self.user,
            kind=AppRunArtifactKind.DUMP_DATA_EXPORT,
            filename='dump.json',
            content_type='application/json',
            size=2,
            content=b'[]',
            expires_at=timezone.now() + timedelta(hours=1),
        )

        self.client.force_authenticate(user=other_user)
        response = self.client.get(f'/api/apps/apps/{self.app.id}/artifacts/{artifact.id}/download/')

        self.assertEqual(response.status_code, 404)


class RunDataTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='run-data-task@example.com',
            password='senha123',
            name='Run Data Task User',
        )
        self.project = Project.objects.create(name='Projeto Run Data Task')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-run-data-task',
            name_dokku='app-run-data-task',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )

    @patch('core.apps.mixins.apps.run_data.DokkuAdapter')
    def test_run_loaddata_sends_fixture_via_stdin_and_removes_upload(self, mock_dokku_cls):
        mock_dokku = Mock()
        mock_dokku.run_in_app_with_stdin.return_value = 'Installed 1 object(s)'
        mock_dokku_cls.return_value = mock_dokku
        artifact = AppRunArtifact.objects.create(
            app=self.app,
            created_by=self.user,
            kind=AppRunArtifactKind.LOAD_DATA_UPLOAD,
            filename='fixture.json',
            content_type='application/json',
            size=2,
            content=b'[]',
            expires_at=timezone.now() + timedelta(hours=1),
        )

        task = AppMixin.run_loaddata
        task.request.id = 'task-loaddata-direct'
        result = task.run(
            app_id=self.app.id,
            artifact_id=str(artifact.id),
            manage_path='manage.py',
            user_id=self.user.id,
        )

        self.assertEqual(result['status'], 'success')
        mock_dokku.run_in_app_with_stdin.assert_called_once()
        self.assertEqual(mock_dokku.run_in_app_with_stdin.call_args.kwargs['stdin_data'], '[]')
        self.assertFalse(AppRunArtifact.objects.filter(id=artifact.id).exists())

    @patch('core.apps.mixins.apps.run_data.DokkuAdapter')
    def test_run_dumpdata_creates_download_artifact_without_logging_content(self, mock_dokku_cls):
        mock_dokku = Mock()
        mock_dokku.run_in_app.return_value = '[{"model":"auth.user"}]'
        mock_dokku_cls.return_value = mock_dokku

        task = AppMixin.run_dumpdata
        task.request.id = 'task-dumpdata-direct'
        result = task.run(
            app_id=self.app.id,
            manage_path='manage.py',
            dump_args=['auth.User'],
            output_filename='users.json',
            user_id=self.user.id,
        )

        artifact = AppRunArtifact.objects.get(app=self.app, kind=AppRunArtifactKind.DUMP_DATA_EXPORT)
        self.assertEqual(result['artifact']['id'], str(artifact.id))
        self.assertEqual(bytes(artifact.content), b'[{"model":"auth.user"}]')
        self.assertFalse(self.app.logs.filter(message__contains='auth.user').exists())


class LastCommitEndpointTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='last-commit@example.com',
            password='senha123',
            name='Last Commit User',
            git_token='token-last-commit',
        )
        self.project = Project.objects.create(name='Projeto Last Commit')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-last-commit',
            name_dokku='app-last-commit',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
            last_commit_sha='abc123def456',
        )
        self.client.force_authenticate(user=self.user)
        cache.clear()

    @patch('github.Github')
    def test_last_commit_uses_cache_until_force_refresh(self, mock_github_cls):
        commit_author = Mock(name='Commit Author')
        commit_author.name = 'Fabroku Bot'
        commit_author.date = Mock(isoformat=Mock(return_value='2026-04-22T12:00:00+00:00'))
        commit = Mock()
        commit.commit.message = 'feat: deploy app'
        commit.commit.author = commit_author
        commit.html_url = 'https://github.com/org/repo/commit/abc123def456'

        repo = Mock()
        repo.get_commit.return_value = commit
        mock_github_cls.return_value.get_repo.return_value = repo

        first_response = self.client.get(f'/api/apps/apps/{self.app.id}/last_commit/')
        second_response = self.client.get(f'/api/apps/apps/{self.app.id}/last_commit/')
        refreshed_response = self.client.get(f'/api/apps/apps/{self.app.id}/last_commit/?refresh=1')

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(refreshed_response.status_code, 200)
        self.assertEqual(first_response.data['sha'], 'abc123def456')
        self.assertEqual(repo.get_commit.call_count, 2)
        self.assertEqual(mock_github_cls.call_count, 2)

    @patch('github.Github')
    def test_last_commit_cache_is_invalidated_when_sha_changes(self, mock_github_cls):
        def make_commit(sha, message):
            commit_author = Mock(name=f'Author {sha}')
            commit_author.name = 'Fabroku Bot'
            commit_author.date = Mock(isoformat=Mock(return_value='2026-04-22T12:00:00+00:00'))
            commit = Mock()
            commit.commit.message = message
            commit.commit.author = commit_author
            commit.html_url = f'https://github.com/org/repo/commit/{sha}'
            return commit

        repo = Mock()
        repo.get_commit.side_effect = lambda sha: make_commit(sha, f'commit {sha}')
        mock_github_cls.return_value.get_repo.return_value = repo

        first_response = self.client.get(f'/api/apps/apps/{self.app.id}/last_commit/')

        self.app.last_commit_sha = 'def789ghi012'
        self.app.save(update_fields=['last_commit_sha'])

        second_response = self.client.get(f'/api/apps/apps/{self.app.id}/last_commit/')

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.data['sha'], 'abc123def456')
        self.assertEqual(second_response.data['sha'], 'def789ghi012')
        self.assertEqual(repo.get_commit.call_count, 2)


class AppVisibilityTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email='owner-apps@example.com',
            password='senha123',
            name='Owner Apps',
        )
        self.fabric_user = User.objects.create_user(
            email='fabric-apps@example.com',
            password='senha123',
            name='Fabric Apps',
            is_fabric=True,
        )
        self.superuser = User.objects.create_user(
            email='superuser-apps@example.com',
            password='senha123',
            name='Superuser Apps',
            is_superuser=True,
            is_staff=True,
        )
        self.project = Project.objects.create(name='Projeto Apps')
        self.project.users.add(self.owner)
        self.app = App.objects.create(
            name='app-visibilidade-teste',
            name_dokku='app-visibilidade-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )

    def test_is_fabric_user_cannot_list_apps_from_other_people_projects(self):
        self.client.force_authenticate(user=self.fabric_user)

        response = self.client.get(f'/api/apps/apps/?project={self.project.id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_superuser_can_list_apps_from_other_people_projects(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(f'/api/apps/apps/?project={self.project.id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.app.id)

    def test_apps_list_avoids_n_plus_one_queries(self):
        collaborator = User.objects.create_user(
            email='collaborator-apps@example.com',
            password='senha123',
            name='Collaborator Apps',
        )
        self.project.users.add(collaborator)
        Service.objects.create(
            name='db-visibilidade-teste',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=self.app,
            project=self.project,
            service_type='postgres',
            container_name='db-visibilidade-teste',
        )

        for index in range(9):
            project = Project.objects.create(name=f'Projeto Apps {index}')
            project.users.add(self.owner, collaborator)
            app = App.objects.create(
                name=f'app-visibilidade-{index}',
                name_dokku=f'app-visibilidade-{index}',
                git='https://github.com/org/repo.git',
                branch='main',
                project=project,
                status='RUNNING',
            )
            Service.objects.create(
                name=f'db-visibilidade-{index}',
                user='postgres',
                password='secret',
                host='localhost',
                port=5432,
                app=app,
                project=project,
                service_type='postgres',
                container_name=f'db-visibilidade-{index}',
            )

        self.client.force_authenticate(user=self.owner)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/apps/apps/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 10)
        self.assertTrue(all(app_data['is_owner'] for app_data in response.data['results']))
        self.assertTrue(all(len(app_data['services']) == 1 for app_data in response.data['results']))
        self.assertLessEqual(len(queries), 7)


class ServiceVisibilityTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email='owner-services@example.com',
            password='senha123',
            name='Owner Services',
        )
        self.fabric_user = User.objects.create_user(
            email='fabric-services@example.com',
            password='senha123',
            name='Fabric Services',
            is_fabric=True,
        )
        self.superuser = User.objects.create_user(
            email='superuser-services@example.com',
            password='senha123',
            name='Superuser Services',
            is_superuser=True,
            is_staff=True,
        )
        self.project = Project.objects.create(name='Projeto Servicos')
        self.project.users.add(self.owner)
        self.app = App.objects.create(
            name='app-servicos-teste',
            name_dokku='app-servicos-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )
        self.service = Service.objects.create(
            name='db-servicos-teste',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=self.app,
            project=self.project,
            service_type='postgres',
            container_name='db-servicos-teste',
        )

    def test_is_fabric_user_cannot_list_services_from_other_people_projects(self):
        self.client.force_authenticate(user=self.fabric_user)

        response = self.client.get(f'/api/apps/services/?project={self.project.id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_superuser_can_list_services_from_other_people_projects(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(f'/api/apps/services/?project={self.project.id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.service.id)


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


@override_settings(BACKEND_URL='https://backend.example.com')
class WebhookSetupTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.request_user = User.objects.create_user(
            email='requester@example.com',
            password='senha123',
            name='Requester',
            git_token='token-requester',
        )
        self.project_user = User.objects.create_user(
            email='owner@example.com',
            password='senha123',
            name='Owner',
            git_token='token-owner',
        )
        self.project = Project.objects.create(name='Projeto Teste')
        self.project.users.add(self.request_user, self.project_user)
        self.app = App.objects.create(
            name='app-webhook-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
        )
        self.client.force_authenticate(user=self.request_user)

    @patch('core.apps.views.GitHubAdapter.create_webhook')
    def test_setup_webhook_uses_project_member_token_when_request_user_cannot_manage_hooks(self, mock_create_webhook):
        mock_create_webhook.side_effect = [
            {
                'status': 'sem permissao para listar webhooks',
                'error': 'token sem acesso a Webhooks',
            },
            {
                'status': 'webhook criado',
                'hook_id': 123,
                'url': 'https://backend.example.com/api/webhooks/github/1/',
            },
        ]

        response = self.client.post(f'/api/apps/apps/{self.app.id}/setup_webhook/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'webhook criado')
        self.assertEqual(response.data['hook_id'], 123)
        self.assertEqual(response.data['configured_by'], 'Owner')
        self.assertEqual(mock_create_webhook.call_args_list[0].kwargs['user_id'], self.request_user.id)
        self.assertEqual(mock_create_webhook.call_args_list[1].kwargs['user_id'], self.project_user.id)

    @patch('core.apps.views.GitHubAdapter.create_webhook')
    def test_setup_webhook_returns_clear_error_when_no_project_token_can_configure(self, mock_create_webhook):
        mock_create_webhook.side_effect = [
            {
                'status': 'sem permissao para listar webhooks',
                'error': 'requester sem Webhooks',
            },
            {
                'status': 'sem permissao para criar webhook',
                'error': 'owner sem Webhooks write',
            },
        ]

        response = self.client.post(f'/api/apps/apps/{self.app.id}/setup_webhook/')

        self.assertEqual(response.status_code, 400)
        self.assertIn('nenhum token do projeto', response.data['error'].lower())
        self.assertEqual(len(response.data['attempts']), 2)
        self.assertEqual(response.data['attempts'][0]['user'], 'Requester')
        self.assertEqual(response.data['attempts'][1]['user'], 'Owner')

    @patch('core.apps.views._find_project_user_for_github_repo')
    def test_diagnose_webhook_reports_project_user_that_can_read_hooks(self, mock_find_project_user_for_github_repo):
        expected_url = f'https://backend.example.com/api/webhooks/github/{self.app.id}/'
        fake_repo = FakeRepo(expected_url)
        mock_find_project_user_for_github_repo.side_effect = [
            (self.project_user, fake_repo, []),
            (self.project_user, fake_repo, []),
        ]

        response = self.client.get(f'/api/apps/apps/{self.app.id}/diagnose_webhook/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['checks']['project_git_token']['ok'])
        self.assertEqual(response.data['checks']['project_git_token']['user'], 'Owner')
        self.assertTrue(response.data['checks']['webhook_exists']['ok'])
        self.assertEqual(response.data['checks']['webhook_exists']['checked_as'], 'Owner')
