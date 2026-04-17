from django.test import TestCase
from rest_framework.test import APIClient

from core.auth_user.models import User
from core.project.models import Project


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
