from rest_framework.test import APIClient, APITestCase

from core.apps.models import App
from core.auth_user.models import User
from core.logs.models import AppLog
from core.project.models import Project


class AppLogVisibilityTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email='owner-logs@example.com',
            password='senha123',
            name='Owner Logs',
        )
        self.fabric_user = User.objects.create_user(
            email='fabric-logs@example.com',
            password='senha123',
            name='Fabric Logs',
            is_fabric=True,
        )
        self.superuser = User.objects.create_user(
            email='superuser-logs@example.com',
            password='senha123',
            name='Superuser Logs',
            is_superuser=True,
            is_staff=True,
        )
        self.project = Project.objects.create(name='Projeto Logs')
        self.project.users.add(self.owner)
        self.app = App.objects.create(
            name='app-logs-teste',
            name_dokku='app-logs-teste',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )
        self.log = AppLog.objects.create(
            app=self.app,
            task_id='task-log-123',
            message='Log privado do projeto',
            progress=50,
        )

    def test_is_fabric_user_cannot_list_logs_from_other_people_projects(self):
        self.client.force_authenticate(user=self.fabric_user)

        response = self.client.get(f'/api/logs/?app={self.app.id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_superuser_can_list_logs_from_other_people_projects(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(f'/api/logs/?app={self.app.id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.log.id)
