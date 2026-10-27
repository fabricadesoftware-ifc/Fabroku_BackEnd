from unittest.mock import patch

from django.db import connection
from django.db.models import ProtectedError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from applications.models import App, AppStatus
from identity.models import User
from projects.models import Project
from service_mgmt.models import Service


class ProjectVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email='owner-project@example.com',
            password='senha123',
            name='Owner Project',
        )
        self.fabric_user = User.objects.create_user(
            email='fabric-project@example.com',
            password='senha123',
            name='Fabric Project',
            is_fabric=True,
        )
        self.collaborator = User.objects.create_user(
            email='collaborator-project@example.com',
            password='senha123',
            name='Collaborator Project',
        )
        self.superuser = User.objects.create_user(
            email='superuser-project@example.com',
            password='senha123',
            name='Superuser Project',
            is_superuser=True,
            is_staff=True,
        )
        self.project = Project.objects.create(name='Projeto de Outro Usuario')
        self.project.users.add(self.owner)

    def test_is_fabric_user_cannot_list_other_people_projects(self):
        self.client.force_authenticate(user=self.fabric_user)

        response = self.client.get('/api/projects/projects/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_superuser_can_list_other_people_projects(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get('/api/projects/projects/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(str(response.data['results'][0]['id']), str(self.project.id))

    def test_member_can_add_and_remove_people_from_team_after_project_creation(self):
        self.client.force_authenticate(user=self.owner)

        add_response = self.client.patch(
            f'/api/projects/projects/{self.project.id}/',
            {'users': [self.owner.id, self.collaborator.id]},
            format='json',
        )

        self.assertEqual(add_response.status_code, 200)
        self.assertCountEqual(add_response.data['users'], [self.owner.id, self.collaborator.id])

        remove_response = self.client.patch(
            f'/api/projects/projects/{self.project.id}/',
            {'users': [self.owner.id]},
            format='json',
        )

        self.assertEqual(remove_response.status_code, 200)
        self.assertEqual(remove_response.data['users'], [self.owner.id])

    def test_member_cannot_remove_themselves_from_team(self):
        self.project.users.add(self.collaborator)
        self.client.force_authenticate(user=self.owner)

        response = self.client.patch(
            f'/api/projects/projects/{self.project.id}/',
            {'users': [self.collaborator.id]},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('users', response.data)

    def test_projects_list_avoids_n_plus_one_queries(self):
        self.client.force_authenticate(user=self.owner)

        for index in range(9):
            project = Project.objects.create(name=f'Projeto {index}')
            project.users.add(self.owner, self.collaborator)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/projects/projects/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 10)
        self.assertLessEqual(len(queries), 6)


@patch('projects.views.delete_service_task.delay')
@patch('projects.views.delete_app_task.delay')
class ProjectSoftDeleteTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email='owner-sd@example.com', password='senha123', name='Owner SD')
        self.outsider = User.objects.create_user(email='out-sd@example.com', password='senha123', name='Out SD')
        self.project = Project.objects.create(name='Projeto SD')
        self.project.users.add(self.owner)
        self.app = App.objects.create(name='app-sd', name_dokku='app-sd', git='https://github.com/x/y', project=self.project)
        self.linked_service = Service.objects.create(
            name='app-sd-db', password='x', host='h', port=5432, app=self.app, project=self.project
        )
        self.standalone_service = Service.objects.create(
            name='solo-db', password='x', host='h', port=5432, project=self.project
        )

    def _delete(self, user):
        self.client.force_authenticate(user=user)
        return self.client.delete(f'/api/projects/projects/{self.project.id}/')

    def test_delete_soft_deletes_project_and_keeps_apps_and_services(self, app_delay, service_delay):
        response = self._delete(self.owner)

        self.assertEqual(response.status_code, 202)
        self.project.refresh_from_db()
        self.assertIsNotNone(self.project.deleted_at)
        self.assertEqual(self.project.deleted_by_id, self.owner.id)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, AppStatus.DELETING)
        self.assertTrue(Service.objects.filter(id=self.linked_service.id).exists())

    def test_delete_dispatches_dokku_cleanup_tasks(self, app_delay, service_delay):
        self._delete(self.owner)

        app_delay.assert_called_once_with(app_id=self.app.id, deleted_by_id=self.owner.id)
        # Service vinculado sai pelo delete_app_task; so o standalone vai direto.
        service_delay.assert_called_once_with(service_id=self.standalone_service.id, deleted_by_id=self.owner.id)

    def test_deleted_project_is_hidden_from_list_and_detail(self, app_delay, service_delay):
        self._delete(self.owner)

        self.assertEqual(self.client.get('/api/projects/projects/').data['count'], 0)
        self.assertEqual(self.client.get(f'/api/projects/projects/{self.project.id}/').status_code, 404)
        self.assertEqual(self._delete(self.owner).status_code, 404)

    def test_non_member_cannot_delete(self, app_delay, service_delay):
        self.assertEqual(self._delete(self.outsider).status_code, 404)
        app_delay.assert_not_called()

    def test_hard_delete_is_blocked_while_apps_exist(self, app_delay, service_delay):
        with self.assertRaises(ProtectedError):
            self.project.delete()

    def test_app_keeps_access_to_soft_deleted_project(self, app_delay, service_delay):
        self._delete(self.owner)

        self.assertEqual(App.objects.get(id=self.app.id).project.name, 'Projeto SD')
