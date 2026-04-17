from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

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
