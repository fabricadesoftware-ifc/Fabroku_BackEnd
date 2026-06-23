import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0023_interactive_runner'),
        ('logs', '0002_applog_delete_logs_applog_app_logs_app_id_64461d_idx_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SSHCommandAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('origin', models.CharField(blank=True, default='', max_length=128)),
                ('command_family', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('sanitized_command', models.TextField()),
                ('command_hash', models.CharField(db_index=True, max_length=64)),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('success', 'Success'),
                            ('failed', 'Failed'),
                            ('timeout', 'Timeout'),
                            ('error', 'Error'),
                        ],
                        db_index=True,
                        default='success',
                        max_length=16,
                    ),
                ),
                ('exit_status', models.IntegerField(blank=True, null=True)),
                ('duration_ms', models.PositiveIntegerField(default=0)),
                ('task_id', models.CharField(blank=True, db_index=True, max_length=255, null=True)),
                ('request_path', models.CharField(blank=True, default='', max_length=512)),
                ('request_method', models.CharField(blank=True, default='', max_length=16)),
                ('error_summary', models.TextField(blank=True, default='')),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                (
                    'app',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='ssh_command_audits',
                        to='apps.app',
                    ),
                ),
                (
                    'service',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='ssh_command_audits',
                        to='apps.service',
                    ),
                ),
                (
                    'user',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='ssh_command_audits',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'SSH Command Audit',
                'verbose_name_plural': 'SSH Command Audits',
                'db_table': 'ssh_command_audits',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='sshcommandaudit',
            index=models.Index(fields=['created_at'], name='idx_ssh_audit_created'),
        ),
        migrations.AddIndex(
            model_name='sshcommandaudit',
            index=models.Index(fields=['origin', 'created_at'], name='idx_ssh_audit_origin'),
        ),
        migrations.AddIndex(
            model_name='sshcommandaudit',
            index=models.Index(fields=['app', 'created_at'], name='idx_ssh_audit_app'),
        ),
        migrations.AddIndex(
            model_name='sshcommandaudit',
            index=models.Index(fields=['user', 'created_at'], name='idx_ssh_audit_user'),
        ),
    ]
