from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.test import APIClient, APITestCase

from applications.models import App
from identity.models import User
from projects.models import Project
from service_mgmt.models import Service


class ServiceDeleteEndpointTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(
            email='delete-service@example.com',
            password='senha123',
            name='Delete Service User',
        )
        project = Project.objects.create(name='Projeto Delete Service')
        project.users.add(user)
        self.user = user
        self.app = App.objects.create(
            name='app-delete-service',
            name_dokku='app-delete-service',
            git='https://github.com/org/delete-service.git',
            branch='main',
            project=project,
            variables={'DATABASE_URL': 'postgres://db-delete-service'},
        )
        self.service = Service.objects.create(
            name='db-delete-service',
            user='postgres',
            password='secret',
            host='localhost',
            port=5432,
            app=self.app,
            project=project,
            service_type='postgres',
            container_name='db-delete-service',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch('service_mgmt.views.delete_service_task.delay')
    def test_delete_endpoint_persists_task_id_on_app(self, mock_delete_delay):
        mock_delete_delay.return_value = Mock(id='task-delete-endpoint-123')

        response = self.client.delete(f'/api/apps/services/{self.service.id}/')

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['task_id'], 'task-delete-endpoint-123')
        self.app.refresh_from_db()
        self.assertEqual(self.app.task_id, 'task-delete-endpoint-123')


class ServiceCreateEndpointTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='service-create@example.com',
            password='senha123',
            name='Service Create User',
        )
        self.project = Project.objects.create(name='Projeto Service Create')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-service-create',
            name_dokku='app-service-create',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )
        self.client.force_authenticate(user=self.user)

    @patch('service_mgmt.serializers.create_service_standalone_task.delay')
    def test_create_standalone_service_allows_missing_name(self, mock_delay):
        mock_delay.return_value = Mock(id='task-standalone-service')

        response = self.client.post(
            '/api/apps/services/',
            {
                'project': self.project.id,
                'service_type': 'postgres',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'provisionando...')
        self.assertEqual(response.data['task_id'], 'task-standalone-service')
        mock_delay.assert_called_once()
        self.assertIsNone(mock_delay.call_args.kwargs['name'])

    @patch('service_mgmt.serializers.create_service_task.delay')
    def test_create_attached_service_allows_missing_name(self, mock_delay):
        mock_delay.return_value = Mock(id='task-attached-service')

        response = self.client.post(
            '/api/apps/services/',
            {
                'app': self.app.id,
                'service_type': 'postgres',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'app-service-create-db')
        self.assertEqual(response.data['env_key'], 'DATABASE_URL')
        service = Service.objects.get(id=response.data['id'])
        mock_delay.assert_called_once_with(
            app_id=self.app.id,
            service_type='postgres',
            service_id=service.id,
        )

    @patch('service_mgmt.serializers.create_service_task.delay')
    def test_create_attached_postgis_reserves_alias_and_image(self, mock_delay):
        self.user.custom_max_services = 5
        self.user.save(update_fields=['custom_max_services'])
        mock_delay.side_effect = [
            Mock(id='task-attached-postgis'),
            Mock(id='task-attached-postgis-2'),
        ]
        Service.objects.create(
            name='primary-db',
            user='postgres',
            password='secret',
            host='dokku-postgres-primary-db',
            port=5432,
            app=self.app,
            project=self.project,
            service_type='postgres',
            container_name='primary-db',
            env_key='DATABASE_URL',
        )

        response = self.client.post(
            '/api/apps/services/',
            {'app': self.app.id, 'service_type': 'postgis'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['service_type'], 'postgis')
        self.assertEqual(response.data['env_key'], 'APP_SERVICE_CREATE_GEO_DB_URL')
        self.assertEqual(response.data['image'], 'postgis/postgis')
        self.assertEqual(response.data['image_version'], '17-3.5')

        second_response = self.client.post(
            '/api/apps/services/',
            {'app': self.app.id, 'service_type': 'postgis'},
            format='json',
        )

        self.assertEqual(second_response.status_code, 201)
        self.assertEqual(second_response.data['name'], 'app-service-create-geo-db-2')
        self.assertEqual(second_response.data['env_key'], 'APP_SERVICE_CREATE_GEO_DB_2_URL')


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
