from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient, APITestCase

from core.apps.models import App, Service
from core.auth_user.models import User
from core.project.models import Project


class UserAdminListTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = User.objects.create_user(
            email='superuser-users@example.com',
            password='senha123',
            name='Superuser Users',
            is_superuser=True,
            is_staff=True,
        )
        self.client.force_authenticate(user=self.superuser)
        cache.clear()

    def test_admin_list_avoids_n_plus_one_on_quota_counts(self):
        tracked_users = []

        for index in range(9):
            user = User.objects.create_user(
                email=f'user-{index}@example.com',
                password='senha123',
                name=f'User {index}',
            )
            project = Project.objects.create(name=f'Projeto User {index}')
            project.users.add(user)
            app = App.objects.create(
                name=f'app-user-{index}',
                name_dokku=f'app-user-{index}',
                git='https://github.com/org/repo.git',
                branch='main',
                project=project,
                status='RUNNING',
            )
            Service.objects.create(
                name=f'db-user-{index}',
                user='postgres',
                password='secret',
                host='localhost',
                port=5432,
                app=app,
                project=project,
                service_type='postgres',
                container_name=f'db-user-{index}',
            )
            tracked_users.append(user)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/auth/users/admin_list/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 10)
        by_email = {item['email']: item for item in response.data}
        tracked_entry = by_email[tracked_users[0].email]
        self.assertEqual(tracked_entry['apps_count'], 1)
        self.assertEqual(tracked_entry['services_count'], 1)
        self.assertLessEqual(len(queries), 4)

    def test_admin_can_promote_and_demote_another_user(self):
        target_user = User.objects.create_user(
            email='target-admin@example.com',
            password='senha123',
            name='Target Admin',
        )

        promote_response = self.client.post(f'/api/auth/users/{target_user.id}/toggle_admin/')

        self.assertEqual(promote_response.status_code, 200)
        self.assertTrue(promote_response.data['is_superuser'])

        target_user.refresh_from_db()
        self.assertTrue(target_user.is_superuser)
        self.assertTrue(target_user.is_staff)

        demote_response = self.client.post(f'/api/auth/users/{target_user.id}/toggle_admin/')

        self.assertEqual(demote_response.status_code, 200)
        self.assertFalse(demote_response.data['is_superuser'])

        target_user.refresh_from_db()
        self.assertFalse(target_user.is_superuser)
        self.assertFalse(target_user.is_staff)

    def test_admin_cannot_change_own_admin_status(self):
        response = self.client.post(f'/api/auth/users/{self.superuser.id}/toggle_admin/')

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.data)

        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_superuser)
        self.assertTrue(self.superuser.is_staff)

    def test_admin_list_uses_cache_when_nothing_changes(self):
        User.objects.create_user(
            email='cached-user@example.com',
            password='senha123',
            name='Cached User',
        )

        first_response = self.client.get('/api/auth/users/admin_list/')

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(len(first_response.data), 2)

        with patch(
            'core.auth_user.views.UserViewSet._get_admin_queryset',
            side_effect=AssertionError('cache should satisfy the second request'),
        ):
            cached_response = self.client.get('/api/auth/users/admin_list/')

        self.assertEqual(cached_response.status_code, 200)
        self.assertEqual(len(cached_response.data), 2)

    def test_admin_list_cache_is_invalidated_when_user_changes(self):
        initial_response = self.client.get('/api/auth/users/admin_list/')

        self.assertEqual(initial_response.status_code, 200)
        self.assertEqual(len(initial_response.data), 1)

        User.objects.create_user(
            email='new-user-after-cache@example.com',
            password='senha123',
            name='New User After Cache',
        )

        refreshed_response = self.client.get('/api/auth/users/admin_list/')

        self.assertEqual(refreshed_response.status_code, 200)
        self.assertEqual(len(refreshed_response.data), 2)
