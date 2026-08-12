import json
from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from applications.models import App, AppProcessScale, AppRunArtifact, AppRunArtifactKind
from applications.process_scale import parse_ps_scale_output, validate_process_quantities
from identity.models import User
from projects.models import Project
from service_mgmt.models import Service


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
    def __init__(self, hook_id, url, active=True, events=None, content_type='json'):
        self.id = hook_id
        self.active = active
        self.events = events if events is not None else ['push']
        self.config = {'url': url, 'content_type': content_type}
        self.raw_data = {'events': self.events}
        self.edited = False

    def edit(self, name, config, events, active):
        self.name = name
        self.config = config
        self.events = events
        self.active = active
        self.edited = True


class FakeRepo:
    def __init__(self, expected_url, hooks=None):
        self.expected_url = expected_url
        self.hooks = hooks

    def get_hooks(self):
        return self.hooks if self.hooks is not None else [FakeHook(77, self.expected_url)]

    def get_branch(self, branch_name):
        return FakeBranch()


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

    @patch('applications.views.manage_app_task.delay')
    def test_stop_endpoint_dispatches_manage_app_task(self, mock_delay):
        mock_delay.return_value = Mock(id='task-stop-123')

        response = self.client.post(f'/api/apps/apps/{self.app.id}/stop/')

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['status'], 'STOPPING')
        self.assertEqual(response.data['task_id'], 'task-stop-123')
        mock_delay.assert_called_once_with(app_id=self.app.id, action='stop')

    @patch('applications.views.AppLogManager')
    @patch('applications.views.manage_app_task.delay')
    @patch('applications.views.AsyncResult')
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



class AppEnvVarsEndpointTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='env@example.com',
            password='senha123',
            name='Env User',
        )
        self.other_user = User.objects.create_user(
            email='outsider-env@example.com',
            password='senha123',
            name='Outsider Env',
        )
        self.project = Project.objects.create(name='Projeto Env')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-env-teste',
            name_dokku='app-env-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
            variables={'OLD_KEY': 'old', 'KEEP': 'same'},
        )

    @patch('applications.views.DokkuAdapter')
    def test_update_env_vars_sets_changed_unsets_removed_and_restarts_running_app(self, mock_dokku_cls):
        self.client.force_authenticate(user=self.user)
        mock_dokku = Mock()
        mock_dokku.set_config.return_value = 'OK'
        mock_dokku.unset_config.return_value = 'OK'
        mock_dokku.restart_app.return_value = 'OK'
        mock_dokku_cls.return_value = mock_dokku

        response = self.client.patch(
            f'/api/apps/apps/{self.app.id}/env_vars/',
            {'variables': {'KEEP': 'changed', 'NEW_KEY': 'new'}},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['updated_keys'], ['KEEP', 'NEW_KEY'])
        self.assertEqual(response.data['removed_keys'], ['OLD_KEY'])
        mock_dokku.set_config.assert_called_once_with(
            app_name='app-env-teste',
            env_vars={'KEEP': 'changed', 'NEW_KEY': 'new'},
            no_restart=True,
        )
        mock_dokku.unset_config.assert_called_once_with(
            app_name='app-env-teste',
            keys=['OLD_KEY'],
            no_restart=True,
        )
        mock_dokku.restart_app.assert_called_once_with('app-env-teste')

        self.app.refresh_from_db()
        self.assertEqual(self.app.variables, {'KEEP': 'changed', 'NEW_KEY': 'new'})

    def test_update_env_vars_rejects_invalid_key(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            f'/api/apps/apps/{self.app.id}/env_vars/',
            {'variables': {'INVALID-KEY': 'value'}},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_non_member_cannot_update_env_vars(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.patch(
            f'/api/apps/apps/{self.app.id}/env_vars/',
            {'variables': {'SECRET_KEY': 'abc'}},
            format='json',
        )

        self.assertEqual(response.status_code, 404)


class AppProcessScaleTests(SimpleTestCase):
    def test_parse_ps_scale_output_ignores_release(self):
        output = """
-----> Scaling for minha-api
proctype: qty
--------: ---
release: 1
web: 1
worker: 0
        """

        self.assertEqual(parse_ps_scale_output(output), {'web': 1, 'worker': 0})

    @override_settings(APP_PROCESS_MAX_INSTANCES=5)
    def test_validate_process_quantities_rejects_web_zero(self):
        with self.assertRaises(ValueError):
            validate_process_quantities({'web': 0})

    def test_validate_process_quantities_rejects_release(self):
        with self.assertRaises(ValueError):
            validate_process_quantities({'release': 1})


class AppProcessScaleEndpointTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='scale@example.com',
            password='senha123',
            name='Scale User',
            is_fabric=True,
        )
        self.member_user = User.objects.create_user(
            email='member-scale@example.com',
            password='senha123',
            name='Member User',
        )
        self.other_user = User.objects.create_user(
            email='outsider-scale@example.com',
            password='senha123',
            name='Outsider User',
        )
        self.project = Project.objects.create(name='Projeto Scale')
        self.project.users.add(self.user)
        self.project.users.add(self.member_user)
        self.app = App.objects.create(
            name='app-scale-teste',
            name_dokku='app-scale-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )

    @patch('applications.views.DokkuAdapter')
    def test_processes_endpoint_syncs_manageable_processes(self, mock_dokku_cls):
        self.client.force_authenticate(user=self.user)
        mock_dokku = Mock()
        mock_dokku.ps_scale_report.return_value = 'release: 1\nweb: 1\nworker: 0\n'
        mock_dokku_cls.return_value = mock_dokku

        response = self.client.get(f'/api/apps/apps/{self.app.id}/processes/?refresh=true')

        self.assertEqual(response.status_code, 200)
        process_names = [process['process_name'] for process in response.data['processes']]
        self.assertEqual(process_names, ['web', 'worker'])
        self.assertFalse(AppProcessScale.objects.filter(app=self.app, process_name='release').exists())

    def test_non_member_cannot_view_processes(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.get(f'/api/apps/apps/{self.app.id}/processes/')

        self.assertEqual(response.status_code, 404)

    def test_regular_member_cannot_view_processes(self):
        self.client.force_authenticate(user=self.member_user)

        response = self.client.get(f'/api/apps/apps/{self.app.id}/processes/')

        self.assertEqual(response.status_code, 403)

    def test_regular_member_cannot_scale_processes(self):
        self.client.force_authenticate(user=self.member_user)

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/scale_processes/',
            {'processes': {'web': 1}},
            format='json',
        )

        self.assertEqual(response.status_code, 403)

    def test_scale_endpoint_rejects_web_zero(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/scale_processes/',
            {'processes': {'web': 0}},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    @patch('applications.views.scale_processes_task.delay')
    @patch('applications.views.DokkuAdapter')
    def test_scale_endpoint_dispatches_task_for_detected_processes(self, mock_dokku_cls, mock_delay):
        self.client.force_authenticate(user=self.user)
        mock_dokku = Mock()
        mock_dokku.ps_scale_report.return_value = 'web: 1\nworker: 0\n'
        mock_dokku_cls.return_value = mock_dokku
        mock_delay.return_value = Mock(id='task-scale-123')

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/scale_processes/',
            {'processes': {'web': 1, 'worker': 1}},
            format='json',
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['task_id'], 'task-scale-123')
        mock_delay.assert_called_once_with(app_id=self.app.id, processes={'web': 1, 'worker': 1})

    @patch('applications.views.AsyncResult')
    def test_get_app_status_returns_cancelled_message_for_revoked_task(self, mock_async_result_cls):
        self.client.force_authenticate(user=self.user)
        self.app.task_id = 'task-redeploy-123'
        self.app.save(update_fields=['task_id'])

        mock_async_result = Mock()
        mock_async_result.state = 'REVOKED'
        mock_async_result_cls.return_value = mock_async_result

        response = self.client.get(f'/api/apps/apps/{self.app.id}/get_app_status/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['state'], 'REVOKED')
        self.assertEqual(response.data['status'], 'Operacao cancelada pelo usuario.')
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

    @patch('applications.views.AsyncResult')
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

    @patch('applications.views.run_migrate_task.delay')
    def test_run_migrate_dispatches_task_with_custom_manage_path(self, mock_delay):
        mock_delay.return_value = Mock(id='task-migrate-123')

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/run_migrate/',
            {'manage_path': 'src/manage.py', 'noinput': True},
            format='json',
        )

        self.assertEqual(response.status_code, 202)
        mock_delay.assert_called_once_with(
            app_id=self.app.id,
            manage_path='src/manage.py',
            noinput=True,
            user_id=self.user.id,
        )

    def test_run_migrate_rejects_unsafe_manage_path(self):
        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/run_migrate/',
            {'manage_path': '../manage.py'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    @patch('applications.views.run_loaddata_task.delay')
    def test_run_loaddata_dispatches_task_with_container_fixture_path(self, mock_delay):
        mock_delay.return_value = Mock(id='task-loaddata-123')

        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/run_loaddata/',
            {'fixture_path': 'fixtures/my_data.json', 'manage_path': 'src/manage.py'},
            format='json',
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(AppRunArtifact.objects.count(), 0)
        mock_delay.assert_called_once_with(
            app_id=self.app.id,
            fixture_path='fixtures/my_data.json',
            manage_path='src/manage.py',
            user_id=self.user.id,
        )

    def test_run_loaddata_rejects_unsafe_manage_path(self):
        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/run_loaddata/',
            {'fixture_path': 'fixtures/my_data.json', 'manage_path': '../manage.py'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AppRunArtifact.objects.count(), 0)

    def test_run_loaddata_rejects_unsafe_fixture_path(self):
        response = self.client.post(
            f'/api/apps/apps/{self.app.id}/run_loaddata/',
            {'fixture_path': '../my_data.json', 'manage_path': 'manage.py'},
            format='json',
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

    @patch('applications.views.run_dumpdata_task.delay')
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




@override_settings(BACKEND_URL='https://backend.example.com', GITHUB_WEBHOOK_SECRET=None)
class WebhookSetupTests(APITestCase):
    def setUp(self):
        cache.clear()
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

    @patch('applications.github_integration.GitHubAdapter.create_webhook')
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
        self.assertTrue(mock_create_webhook.call_args_list[0].kwargs['force_update'])

    @patch('applications.github_integration.GitHubAdapter.create_webhook')
    def test_setup_webhook_tries_next_project_token_after_unexpected_error(self, mock_create_webhook):
        mock_create_webhook.side_effect = [
            RuntimeError('temporary GitHub failure'),
            {
                'status': 'webhook criado',
                'hook_id': 456,
                'url': f'https://backend.example.com/api/webhooks/github/{self.app.id}/',
            },
        ]

        response = self.client.post(f'/api/apps/apps/{self.app.id}/setup_webhook/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['hook_id'], 456)
        self.assertEqual(response.data['attempts'][0]['status'], 'erro inesperado')
        self.assertEqual(mock_create_webhook.call_count, 2)

    @patch('applications.github_integration.GitHubAdapter.create_webhook')
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

    @patch('applications.github_integration.GitHubAdapter.create_webhook')
    def test_setup_webhook_accepts_repaired_existing_hook(self, mock_create_webhook):
        mock_create_webhook.return_value = {
            'status': 'webhook atualizado',
            'hook_id': 123,
            'url': f'https://backend.example.com/api/webhooks/github/{self.app.id}/',
        }

        response = self.client.post(f'/api/apps/apps/{self.app.id}/setup_webhook/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'webhook atualizado')
        self.assertEqual(response.data['hook_id'], 123)

    @patch('applications.views._find_project_user_for_github_repo')
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

    @patch('applications.views._find_project_user_for_github_repo')
    def test_diagnose_webhook_reports_incomplete_hook_as_not_ok(self, mock_find_project_user_for_github_repo):
        expected_url = f'https://backend.example.com/api/webhooks/github/{self.app.id}/'
        fake_repo = FakeRepo(
            expected_url,
            hooks=[FakeHook(77, expected_url.rstrip('/'), active=False, events=['issues'], content_type='form')],
        )
        mock_find_project_user_for_github_repo.side_effect = [
            (self.project_user, fake_repo, []),
            (self.project_user, fake_repo, []),
        ]

        response = self.client.get(f'/api/apps/apps/{self.app.id}/diagnose_webhook/')

        self.assertEqual(response.status_code, 200)
        webhook_check = response.data['checks']['webhook_exists']
        self.assertFalse(webhook_check['ok'])
        self.assertEqual(webhook_check['matching_hooks'], 1)
        self.assertEqual(webhook_check['usable_hooks'], 0)
        self.assertIn('precisa ser reparado', webhook_check['message'])

    @patch('infrastructure.adapters.utils.git_webhook.deploy_app_task.delay')
    def test_github_webhook_accepts_branch_names_with_slashes(self, mock_redeploy):
        mock_redeploy.return_value = Mock(id='task-webhook-123')
        self.app.branch = 'feature/auto-deploy'
        self.app.save(update_fields=['branch'])

        response = self.client.post(
            f'/api/webhooks/github/{self.app.id}/',
            data=json.dumps({
                'ref': 'refs/heads/feature/auto-deploy',
                'after': 'abc123def4567890',
                'pusher': {'name': 'student'},
            }),
            content_type='application/json',
            HTTP_X_GITHUB_EVENT='push',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'deploy_started')
        mock_redeploy.assert_called_once_with(app_id=self.app.id, commit='abc123def4567890')

    @patch('infrastructure.adapters.utils.git_webhook.deploy_app_task.delay')
    def test_github_webhook_ignores_repeated_delivery_id(self, mock_redeploy):
        mock_redeploy.return_value = Mock(id='task-webhook-deduplicated')
        payload = json.dumps({
            'ref': 'refs/heads/main',
            'after': 'abc123def4567890',
            'pusher': {'name': 'student'},
        })
        headers = {
            'content_type': 'application/json',
            'HTTP_X_GITHUB_EVENT': 'push',
            'HTTP_X_GITHUB_DELIVERY': 'delivery-test-123',
        }

        first_response = self.client.post(
            f'/api/webhooks/github/{self.app.id}/',
            data=payload,
            **headers,
        )
        duplicate_response = self.client.post(
            f'/api/webhooks/github/{self.app.id}/',
            data=payload,
            **headers,
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.json()['status'], 'deploy_started')
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(duplicate_response.json()['status'], 'duplicate')
        mock_redeploy.assert_called_once_with(app_id=self.app.id, commit='abc123def4567890')

    @patch('infrastructure.adapters.utils.git_webhook.deploy_app_task.delay')
    def test_github_webhook_releases_delivery_when_task_cannot_be_queued(self, mock_redeploy):
        payload = json.dumps({
            'ref': 'refs/heads/main',
            'after': 'abc123def4567890',
            'pusher': {'name': 'student'},
        })
        headers = {
            'content_type': 'application/json',
            'HTTP_X_GITHUB_EVENT': 'push',
            'HTTP_X_GITHUB_DELIVERY': 'delivery-queue-failure-123',
        }
        mock_redeploy.side_effect = RuntimeError('broker unavailable')

        with self.assertRaisesRegex(RuntimeError, 'broker unavailable'):
            self.client.post(
                f'/api/webhooks/github/{self.app.id}/',
                data=payload,
                **headers,
            )

        mock_redeploy.side_effect = None
        mock_redeploy.return_value = Mock(id='task-webhook-retry')
        retry_response = self.client.post(
            f'/api/webhooks/github/{self.app.id}/',
            data=payload,
            **headers,
        )

        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(retry_response.json()['status'], 'deploy_started')
        self.assertEqual(mock_redeploy.call_count, 2)

    @patch('infrastructure.adapters.git_mixins.repo.Github')
    def test_create_webhook_repairs_incomplete_existing_hook(self, mock_github_cls):
        from infrastructure.adapters import GitHubAdapter

        expected_url = f'https://backend.example.com/api/webhooks/github/{self.app.id}/'
        hook = FakeHook(99, expected_url, active=False, events=['issues'], content_type='form')
        mock_github_cls.return_value.get_repo.return_value = FakeRepo(expected_url, hooks=[hook])

        result = GitHubAdapter().create_webhook(
            repo_name='org/repo',
            app_id=self.app.id,
            user_id=self.request_user.id,
        )

        self.assertEqual(result['status'], 'webhook atualizado')
        self.assertTrue(hook.edited)
        self.assertTrue(hook.active)
        self.assertEqual(hook.events, ['push'])
        self.assertEqual(hook.config['content_type'], 'json')

    @patch('infrastructure.adapters.git_mixins.repo.Github')
    def test_create_webhook_only_rewrites_valid_hook_when_forced(self, mock_github_cls):
        from infrastructure.adapters import GitHubAdapter

        expected_url = f'https://backend.example.com/api/webhooks/github/{self.app.id}/'
        hook = FakeHook(100, expected_url)
        mock_github_cls.return_value.get_repo.return_value = FakeRepo(expected_url, hooks=[hook])
        adapter = GitHubAdapter()

        existing_result = adapter.create_webhook(
            repo_name='org/repo',
            app_id=self.app.id,
            user_id=self.request_user.id,
        )
        self.assertEqual(existing_result['status'], 'webhook ja existe')
        self.assertFalse(hook.edited)

        updated_result = adapter.create_webhook(
            repo_name='org/repo',
            app_id=self.app.id,
            user_id=self.request_user.id,
            force_update=True,
        )
        self.assertEqual(updated_result['status'], 'webhook atualizado')
        self.assertTrue(hook.edited)
