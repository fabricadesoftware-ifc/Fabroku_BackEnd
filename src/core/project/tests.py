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
