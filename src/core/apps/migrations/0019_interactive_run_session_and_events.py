import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0018_apprunartifact'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InteractiveRunSession',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    'command_kind',
                    models.CharField(
                        choices=[('django_createsuperuser', 'Django Createsuperuser')],
                        max_length=64,
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('pending', 'Pending'),
                            ('running', 'Running'),
                            ('awaiting_input', 'Awaiting Input'),
                            ('completed', 'Completed'),
                            ('failed', 'Failed'),
                            ('cancelled', 'Cancelled'),
                            ('expired', 'Expired'),
                        ],
                        default='pending',
                        max_length=32,
                    ),
                ),
                ('manage_path', models.CharField(default='manage.py', max_length=255)),
                ('task_id', models.CharField(blank=True, db_index=True, max_length=255, null=True)),
                ('cancel_requested', models.BooleanField(default=False)),
                ('prompt_counter', models.PositiveIntegerField(default=0)),
                ('awaiting_prompt_id', models.CharField(blank=True, max_length=64, null=True)),
                ('awaiting_prompt_text', models.CharField(blank=True, max_length=255, null=True)),
                ('awaiting_prompt_secret', models.BooleanField(default=False)),
                ('pending_answer_prompt_id', models.CharField(blank=True, max_length=64, null=True)),
                ('pending_answer_ciphertext', models.BinaryField(blank=True, null=True)),
                ('pending_answer_received_at', models.DateTimeField(blank=True, null=True)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('last_activity_at', models.DateTimeField(db_index=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'app',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='interactive_sessions',
                        to='apps.app',
                    ),
                ),
                (
                    'created_by',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='interactive_run_sessions',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Interactive Run Session',
                'verbose_name_plural': 'Interactive Run Sessions',
                'db_table': 'interactive_run_sessions',
            },
        ),
        migrations.CreateModel(
            name='InteractiveRunEvent',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                (
                    'event_type',
                    models.CharField(
                        choices=[
                            ('status', 'Status'),
                            ('output', 'Output'),
                            ('prompt', 'Prompt'),
                            ('complete', 'Complete'),
                            ('error', 'Error'),
                        ],
                        max_length=32,
                    ),
                ),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    'session',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='events',
                        to='apps.interactiverunsession',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Interactive Run Event',
                'verbose_name_plural': 'Interactive Run Events',
                'db_table': 'interactive_run_events',
            },
        ),
        migrations.AddIndex(
            model_name='interactiverunsession',
            index=models.Index(fields=['app', 'status'], name='idx_irs_app_status'),
        ),
        migrations.AddIndex(
            model_name='interactiverunsession',
            index=models.Index(fields=['created_by', 'created_at'], name='idx_irs_user_created'),
        ),
        migrations.AddIndex(
            model_name='interactiverunevent',
            index=models.Index(fields=['session', 'id'], name='idx_ire_session_id'),
        ),
    ]
