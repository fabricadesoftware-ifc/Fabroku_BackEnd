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
        self.admin_user = User.objects.create_user(
            email='admin-project@example.com',
            password='senha123',
            name='Admin Project',
            is_fabric=True,
        )
        self.project = Project.objects.create(name='Projeto de Outro Usuario')
        self.project.users.add(self.owner)

    def test_is_fabric_user_can_list_other_people_projects(self):
        self.client.force_authenticate(user=self.admin_user)

        response = self.client.get('/api/projects/projects/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(str(response.data['results'][0]['id']), str(self.project.id))
