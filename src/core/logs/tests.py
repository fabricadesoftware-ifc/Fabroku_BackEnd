# ruff: noqa: PT009, PT019

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from core.apps.models import App
from core.auth_user.models import User
from core.logs.models import AppLog, SSHCommandAudit
from core.logs.ssh_audit import begin_ssh_audit, finish_ssh_audit, ssh_audit_context
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

    @patch('core.logs.views.has_live_runner', return_value=True)
    @patch('core.logs.views.get_logstream_redis')
    @patch('core.logs.views.read_buffer')
    @patch('core.logs.views.app_stream_subscription')
    def test_runtime_sse_sends_snapshot_from_redis_buffer(
        self,
        mock_subscription,
        mock_read_buffer,
        mock_get_redis,
        _mock_has_runner,
    ):
        redis_client = MagicMock()
        pubsub = MagicMock()
        redis_client.pubsub.return_value = pubsub
        mock_get_redis.return_value = redis_client
        mock_read_buffer.return_value = [
            {'line': 'linha 1'},
            {'line': 'linha 2'},
        ]

        @contextmanager
        def fake_subscription(_app_id):
            yield redis_client, 'subscriber-test'

        mock_subscription.side_effect = fake_subscription
        self.client.force_authenticate(user=self.owner)

        response = self.client.get(f'/api/logs/app-runtime-stream/?app={self.app.id}&tail=200')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/event-stream')
        first_chunk = next(response.streaming_content).decode('utf-8')
        self.assertIn('event: snapshot', first_chunk)
        self.assertIn('linha 1', first_chunk)
        self.assertIn('linha 2', first_chunk)

    def test_runtime_sse_rejects_non_member(self):
        outsider = User.objects.create_user(
            email='outsider-logs@example.com',
            password='senha123',
            name='Outsider Logs',
        )
        self.client.force_authenticate(user=outsider)

        response = self.client.get(f'/api/logs/app-runtime-stream/?app={self.app.id}&tail=200')

        self.assertEqual(response.status_code, 403)

    @patch('core.logs.views.has_live_runner', return_value=False)
    @patch('core.logs.views.get_logstream_redis')
    def test_runtime_sse_returns_503_when_logstream_runner_is_down(self, mock_get_redis, _mock_has_runner):
        mock_get_redis.return_value = MagicMock()
        self.client.force_authenticate(user=self.owner)

        response = self.client.get(f'/api/logs/app-runtime-stream/?app={self.app.id}&tail=200')

        self.assertEqual(response.status_code, 503)


class SSHCommandAuditTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='audit@example.com',
            password='senha123',
            name='Audit User',
        )
        self.project = Project.objects.create(name='Projeto Audit')
        self.project.users.add(self.user)
        self.app = App.objects.create(
            name='app-audit',
            name_dokku='app-audit',
            git='https://github.com/org/repo.git',
            branch='main',
            project=self.project,
            status='RUNNING',
        )

    @override_settings(SSH_AUDIT_ENABLED=True)
    def test_ssh_audit_persists_sanitized_command_with_context(self):
        with ssh_audit_context(
            origin='test',
            user_id=self.user.id,
            app_id=self.app.id,
            request_path='/api/test/',
            request_method='POST',
        ):
            audit = begin_ssh_audit(
                'config:set app-audit SECRET_KEY=super-secret DATABASE_URL=postgres://u:p@example/db DEBUG=True'
            )
            finish_ssh_audit(audit, status='success', exit_status=0)

        record = SSHCommandAudit.objects.get()
        self.assertEqual(record.origin, 'test')
        self.assertEqual(record.user, self.user)
        self.assertEqual(record.app, self.app)
        self.assertEqual(record.command_family, 'config')
        self.assertEqual(record.status, 'success')
        self.assertIn('SECRET_KEY=[oculto]', record.sanitized_command)
        self.assertIn('DATABASE_URL=[oculto]', record.sanitized_command)
        self.assertNotIn('super-secret', record.sanitized_command)
        self.assertEqual(record.request_path, '/api/test/')

    @override_settings(SSH_AUDIT_RETENTION_DAYS=7)
    def test_prune_ssh_command_audit_removes_old_records(self):
        old_record = SSHCommandAudit.objects.create(
            app=self.app,
            user=self.user,
            origin='old',
            command_family='logs',
            sanitized_command='logs app-audit -n 200',
            command_hash='old',
            created_at=timezone.now() - timedelta(days=10),
        )
        fresh_record = SSHCommandAudit.objects.create(
            app=self.app,
            user=self.user,
            origin='fresh',
            command_family='logs',
            sanitized_command='logs app-audit -n 200',
            command_hash='fresh',
            created_at=timezone.now(),
        )

        call_command('prune_ssh_command_audit')

        self.assertFalse(SSHCommandAudit.objects.filter(id=old_record.id).exists())
        self.assertTrue(SSHCommandAudit.objects.filter(id=fresh_record.id).exists())
