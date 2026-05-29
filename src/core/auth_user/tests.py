from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient, APITestCase

from core.adapters.utils.git_email import verify_git_email
from core.apps.models import App, Service
from core.auth_user.allowed_emails.models import AllowedEmail
from core.auth_user.models import User
from core.project.models import Project


class GitEmailPolicyTests(APITestCase):
    @override_settings(
        AUTH_ALLOWED_EMAIL_DOMAINS=['estudantes.ifc.edu.br'],
        AUTH_ALLOW_ALL_VERIFIED_EMAILS=False,
    )
    def test_default_policy_allows_verified_ifc_student_email(self):
        approved_email = verify_git_email([
            {'email': 'aluno@estudantes.ifc.edu.br', 'verified': True},
        ])

        self.assertEqual(approved_email, 'aluno@estudantes.ifc.edu.br')

    @override_settings(
        AUTH_ALLOWED_EMAIL_DOMAINS=['estudantes.ifc.edu.br'],
        AUTH_ALLOW_ALL_VERIFIED_EMAILS=False,
    )
    def test_default_policy_blocks_unlisted_external_email(self):
        approved_email = verify_git_email([
            {'email': 'pessoa@example.com', 'verified': True},
        ])

        self.assertIsNone(approved_email)

    @override_settings(
        AUTH_ALLOWED_EMAIL_DOMAINS=['estudantes.ifc.edu.br'],
        AUTH_ALLOW_ALL_VERIFIED_EMAILS=False,
    )
    def test_policy_allows_email_registered_in_allowlist(self):
        AllowedEmail.objects.create(email='professor@example.com', is_active=True)

        approved_email = verify_git_email([
            {'email': 'professor@example.com', 'verified': True},
        ])

        self.assertEqual(approved_email, 'professor@example.com')

    @override_settings(AUTH_ALLOWED_EMAIL_DOMAINS=['empresa.com'], AUTH_ALLOW_ALL_VERIFIED_EMAILS=False)
    def test_policy_allows_configured_domain(self):
        approved_email = verify_git_email([
            {'email': 'dev@empresa.com', 'verified': True},
        ])

        self.assertEqual(approved_email, 'dev@empresa.com')

    @override_settings(AUTH_ALLOWED_EMAIL_DOMAINS=[], AUTH_ALLOW_ALL_VERIFIED_EMAILS=True)
    def test_policy_can_allow_any_verified_email(self):
        approved_email = verify_git_email([
            {'email': 'old@example.com', 'verified': True},
            {'email': 'primary@example.com', 'verified': True, 'primary': True},
        ])

        self.assertEqual(approved_email, 'primary@example.com')

    @override_settings(AUTH_ALLOWED_EMAIL_DOMAINS=['empresa.com'], AUTH_ALLOW_ALL_VERIFIED_EMAILS=True)
    def test_policy_never_allows_unverified_email(self):
        approved_email = verify_git_email([
            {'email': 'dev@empresa.com', 'verified': False},
        ])

        self.assertIsNone(approved_email)


class PlatformConfigTests(APITestCase):
    @override_settings(
        FABROKU_ORGANIZATION_NAME='Minha Organizacao',
        FABROKU_PRIVILEGED_ROLE_LABEL='Equipe interna',
        FABROKU_REGULAR_ROLE_LABEL='Usuario',
        FABROKU_APP_DOMAIN_SUFFIX='.apps.example.com',
    )
    def test_platform_config_is_public_and_uses_installation_settings(self):
        response = self.client.get('/api/platform/config/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['organization_name'], 'Minha Organizacao')
        self.assertEqual(response.data['privileged_role_label'], 'Equipe interna')
        self.assertEqual(response.data['regular_role_label'], 'Usuario')
        self.assertEqual(response.data['app_domain_suffix'], '.apps.example.com')


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
