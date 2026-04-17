from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from core.adapters.dokku_mixins.dokku_config import DokkuConfigMixin
from core.apps.mixins.apps.create_app import CreateAppMixin
from core.apps.mixins.apps.redeploy_app import RedeployAppMixin
from core.apps.models import App
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


class FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def success(self, *args, **kwargs):
        return None

    def dokku(self, *args, **kwargs):
        return None


class FakeRedeployDokkuAdapter:
    def __init__(self):
        self.set_config_calls = []

    def exists_app(self, app_name: str) -> bool:
        return True

    def set_config(self, **kwargs):
        self.set_config_calls.append(kwargs)
        return 'OK'

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

        self.assertEqual(output, 'SECRET_KEY: OK')
        self.assertEqual(adapter.commands, ['config:set --no-restart my-app SECRET_KEY="abc"'])


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

    @patch('core.apps.mixins.apps.redeploy_app.AppLogManager', return_value=FakeLogger())
    @patch('core.apps.mixins.apps.redeploy_app.DokkuAdapter')
    @patch('core.apps.mixins.apps.redeploy_app.RedeployAppMixin._get_git_token', return_value=None)
    def test_redeploy_syncs_env_vars_without_restart(self, mock_get_git_token, mock_dokku_cls, mock_logger_cls):
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

        fake_dokku = FakeRedeployDokkuAdapter()
        mock_dokku_cls.return_value = fake_dokku
        task = RedeployAppMixin.redeploy_app

        with patch.object(task, 'update_state') as mock_update_state:
            task.request.id = 'task-123'
            result = task.run(app_id=app.id, commit=None)

        self.assertEqual(result['status'], 'success')
        self.assertTrue(mock_update_state.called)
        self.assertEqual(fake_dokku.set_config_calls, [
            {
                'app_name': 'app-redeploy-teste',
                'env_vars': {'SECRET_KEY': 'abc'},
                'no_restart': True,
            }
        ])


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
                'status': 'sem permissão para listar webhooks',
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
                'status': 'sem permissão para listar webhooks',
                'error': 'requester sem Webhooks',
            },
            {
                'status': 'sem permissão para criar webhook',
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
