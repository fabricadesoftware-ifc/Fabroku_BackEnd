"""Regressões das correções de segurança (auditoria de 2026-11).

Roda pelo runner do Django (como o CI):
    PYTHONPATH=.. python manage.py test tests.unit.test_security_hardening
"""
from types import SimpleNamespace
from unittest.mock import patch

import paramiko
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from applications.serializers import AppSerializer, EnvVarsUpdateSerializer
from core.apps.mixins.apps.run_command import is_command_allowed
from core.auth_user.authentication import CookieJWTAuthentication, trusted_cookie_origins
from infrastructure.adapters.ssh import SSHAdapter
from service_mgmt.serializers import ServiceSerializer
from tests.factories.models import AppFactory, ProjectFactory, UserFactory


class CommandWhitelistTests(SimpleTestCase):
    def test_allows_regular_commands(self):
        for command in (
            'python manage.py migrate',
            'python manage.py collectstatic --noinput',
            'python manage.py migrate app 0003',
            'npm run build',
            'npx prisma migrate deploy',
        ):
            with self.subTest(command=command):
                self.assertTrue(is_command_allowed(command))

    def test_blocks_interpreters_and_code_eval(self):
        for command in (
            'python manage.py shell -c "__import__(\'os\').system(\'id\')"',
            'python manage.py shell',
            'python manage.py dbshell',
            'python manage.py shell_plus',
            'node ace repl',
            'php artisan tinker',
            'rails runner "puts 1"',
            'rails console',
            'bundle exec ruby -e "puts 1"',
            'npm run x -- -e 1',
        ):
            with self.subTest(command=command):
                self.assertFalse(is_command_allowed(command))

    def test_blocks_shell_metacharacters_and_newlines(self):
        for command in (
            'python manage.py migrate; id',
            'python manage.py migrate\nid',
            'python manage.py migrate ${IFS}id',
            'python manage.py migrate $(id)',
            'python manage.py migrate && id',
        ):
            with self.subTest(command=command):
                self.assertFalse(is_command_allowed(command))


def _serializer(user, data, instance=None, partial=False):
    request = SimpleNamespace(user=user)
    return AppSerializer(instance=instance, data=data, partial=partial, context={'request': request})


class AppSerializerHardeningTests(TestCase):
    def setUp(self):
        self.fabric = UserFactory(is_fabric=True)
        self.project = ProjectFactory(users=[self.fabric])

    def test_rejects_branch_with_shell_or_flag_characters(self):
        for branch in ('main; reboot', 'main --force', '-x', 'a..b', 'main$(id)', 'ma in'):
            with self.subTest(branch=branch):
                serializer = _serializer(self.fabric, {
                    'name': 'app-branch', 'git': 'https://github.com/o/r', 'project': str(self.project.id),
                    'branch': branch,
                })
                self.assertFalse(serializer.is_valid())
                self.assertIn('branch', serializer.errors)

    def test_accepts_branch_with_slashes(self):
        serializer = _serializer(self.fabric, {
            'name': 'app-branch', 'git': 'https://github.com/o/r', 'project': str(self.project.id),
            'branch': 'feature/auto-deploy_1.2',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_project_the_user_is_not_member_of(self):
        outsider_project = ProjectFactory()
        serializer = _serializer(self.fabric, {
            'name': 'app-alheio', 'git': 'https://github.com/o/r', 'project': str(outsider_project.id),
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('project', serializer.errors)

    def test_rejects_reserved_env_var_prefix_on_create(self):
        serializer = _serializer(self.fabric, {
            'name': 'app-env', 'git': 'https://github.com/o/r', 'project': str(self.project.id),
            'variables': {'DOKKU_PROXY_PORT_MAP': 'http:22:5000'},
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('variables', serializer.errors)

    def test_patch_cannot_point_name_dokku_at_platform_or_other_app(self):
        own_app = AppFactory(project=self.project, name='meu-app', name_dokku='meu-app', created_by=self.fabric)
        AppFactory(name='app-de-outro', name_dokku='app-de-outro')

        for target in ('fabroku-api', 'app-de-outro', 'outro-nome'):
            with self.subTest(target=target):
                serializer = _serializer(self.fabric, {'name_dokku': target}, instance=own_app, partial=True)
                self.assertFalse(serializer.is_valid())
                self.assertIn('name_dokku', serializer.errors)

    def test_create_rejects_reserved_custom_name_dokku(self):
        serializer = _serializer(self.fabric, {
            'name': 'app-novo', 'git': 'https://github.com/o/r', 'project': str(self.project.id),
            'name_dokku': 'fabroku-api',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('name_dokku', serializer.errors)


class EnvVarsReservedPrefixTests(SimpleTestCase):
    def test_env_vars_endpoint_rejects_dokku_prefix(self):
        serializer = EnvVarsUpdateSerializer(data={'variables': {'dokku_app_restore': '0'}})
        self.assertFalse(serializer.is_valid())


class ServiceMembershipTests(TestCase):
    def test_cannot_attach_service_to_app_of_other_project(self):
        attacker = UserFactory()
        victim_app = AppFactory()
        serializer = ServiceSerializer(
            data={'app': victim_app.id, 'service_type': 'postgres'},
            context={'request': SimpleNamespace(user=attacker)},
        )
        self.assertFalse(serializer.is_valid())


@override_settings(FRONTEND_URL='https://fabroku.example.com', BACKEND_URL='https://api.example.com')
class CookieCsrfOriginTests(TestCase):
    def setUp(self):
        trusted_cookie_origins.cache_clear()
        self.user = UserFactory()
        self.token = str(RefreshToken.for_user(self.user).access_token)
        self.factory = RequestFactory()

    def tearDown(self):
        trusted_cookie_origins.cache_clear()

    def _authenticate(self, method, **headers):
        request = getattr(self.factory, method)('/api/apps/apps/', **headers)
        request.COOKIES['access_token'] = self.token
        return CookieJWTAuthentication().authenticate(request)

    def test_cross_site_post_with_cookie_is_rejected(self):
        for origin in ('https://aluno.class.example.com', 'null', 'https://evil.com'):
            with self.subTest(origin=origin), self.assertRaises(PermissionDenied):
                self._authenticate('post', HTTP_ORIGIN=origin)

    def test_frontend_post_and_cross_site_get_are_allowed(self):
        user, _ = self._authenticate('post', HTTP_ORIGIN='https://fabroku.example.com')
        self.assertEqual(user.id, self.user.id)
        user, _ = self._authenticate('get', HTTP_ORIGIN='https://evil.com')
        self.assertEqual(user.id, self.user.id)

    def test_non_browser_client_without_origin_is_allowed(self):
        user, _ = self._authenticate('post')
        self.assertEqual(user.id, self.user.id)

    def test_end_to_end_cross_site_delete_is_forbidden(self):
        app = AppFactory(project=ProjectFactory(users=[self.user]), name_dokku='app-x')
        client = APIClient()
        client.cookies['access_token'] = self.token
        with patch('applications.views.dispatch_app_task') as dispatch:
            response = client.delete(f'/api/apps/apps/{app.id}/', HTTP_ORIGIN='https://aluno.class.example.com')
        self.assertEqual(response.status_code, 403)
        dispatch.assert_not_called()


class SSHHostKeyPinningTests(SimpleTestCase):
    def test_without_pinned_key_keeps_legacy_autoadd(self):
        adapter = SSHAdapter('dokku.example.com', 'dokku', 'unused', 22)
        client = adapter._new_client()
        self.assertIsInstance(client._policy, paramiko.AutoAddPolicy)

    def test_pinned_key_uses_reject_policy(self):
        rsa = paramiko.RSAKey.generate(1024)
        host_key = f'{rsa.get_name()} {rsa.get_base64()}'
        adapter = SSHAdapter('dokku.example.com', 'dokku', 'unused', 1022, host_key=host_key)
        client = adapter._new_client()
        self.assertIsInstance(client._policy, paramiko.RejectPolicy)
        stored = client.get_host_keys().lookup('[dokku.example.com]:1022')
        self.assertEqual(stored[rsa.get_name()].get_base64(), rsa.get_base64())
