import socket
from unittest.mock import ANY, Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from core.adapters.dokku_mixins.dokku_apps import DokkuAppsMixin
from core.adapters.dokku_mixins.dokku_config import DokkuConfigMixin
from core.adapters.ssh import SSHAdapter
from core.apps.mixins import AppMixin
from core.apps.mixins.apps.create_app import CreateAppMixin
from core.apps.mixins.apps.redeploy_app import RedeployAppMixin
from core.apps.models import App, Service
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

    def set_config(self, **kwargs):
        self.set_config_calls.append(kwargs)
        return self.set_config_output

    def sync_git_streaming(self, **kwargs):
        return 'Sync complete'

    def get_app_domain(self, app_name: str) -> str:
        return 'app.example.com'

    def enable_letsencrypt(self, app_name: str) -> str:
        return 'OK'


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
    @patch('core.apps.mixins.services.link_service.ManageAppMixin.manage_app_task.delay')
    @patch('core.apps.mixins.services.link_service.DokkuAdapter')
    def test_link_service_allows_unlinked_service_without_none_id_error(self, mock_dokku_cls, mock_restart_delay):
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
        mock_dokku_cls.return_value = mock_dokku
        mock_restart_delay.return_value.get.return_value = 'restart ok'

        task = AppMixin.link_service
        with patch.object(task, 'update_state'):
            task.request.id = 'task-link-123'
            result = task.run(service_id=service.id, app_id=app.id)

        self.assertEqual(result['status'], 'linked')
        service.refresh_from_db()
        app.refresh_from_db()
        self.assertEqual(service.app_id, app.id)
        self.assertEqual(app.variables['DATABASE_URL'], 'postgres://db-link-teste')


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


class ServiceVisibilityTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email='owner-services@example.com',
            password='senha123',
            name='Owner Services',
        )
        self.admin_user = User.objects.create_user(
            email='admin-services@example.com',
            password='senha123',
            name='Admin Services',
            is_fabric=True,
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

    def test_is_fabric_user_can_list_services_from_other_people_projects(self):
        self.client.force_authenticate(user=self.admin_user)

        response = self.client.get(f'/api/apps/services/?project={self.project.id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.service.id)


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
