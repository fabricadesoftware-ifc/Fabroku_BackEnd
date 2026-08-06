import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: registers InteractiveRunRunner/Session/Event/AuditChunk under
    `interactive_sessions`.

    No database_operations — the `interactive_run_*` tables (and all their
    indexes/constraints) already exist, created by core.apps's original
    migrations. This just moves Django's bookkeeping of these four models to
    their new app label; see core/apps/migrations/0029_... for the matching
    removal on the other side of the move.
    """

    initial = True

    dependencies = [
        ('applications', '0001_initial'),
        ('service_mgmt', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='InteractiveRunRunner',
                    fields=[
                        (
                            'runner_id',
                            models.CharField(max_length=128, primary_key=True, serialize=False),
                        ),
                        ('hostname', models.CharField(blank=True, default='', max_length=255)),
                        ('pid', models.PositiveIntegerField(default=0)),
                        ('max_sessions', models.PositiveIntegerField(default=1)),
                        ('active_sessions', models.PositiveIntegerField(default=0)),
                        ('started_at', models.DateTimeField(default=django.utils.timezone.now)),
                        ('last_heartbeat_at', models.DateTimeField(db_index=True)),
                        ('metadata', models.JSONField(blank=True, default=dict)),
                    ],
                    options={
                        'verbose_name': 'Interactive Run Runner',
                        'verbose_name_plural': 'Interactive Run Runners',
                        'db_table': 'interactive_run_runners',
                        'indexes': [
                            models.Index(fields=['last_heartbeat_at'], name='idx_irr_last_heartbeat')
                        ],
                    },
                ),
                migrations.CreateModel(
                    name='InteractiveRunSession',
                    fields=[
                        (
                            'id',
                            models.UUIDField(
                                default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                            ),
                        ),
                        (
                            'command_kind',
                            models.CharField(
                                choices=[
                                    ('django_createsuperuser', 'Django Createsuperuser'),
                                    ('postgres_connect', 'Postgres Connect'),
                                ],
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
                        (
                            'runner_id',
                            models.CharField(blank=True, db_index=True, max_length=128, null=True),
                        ),
                        ('claimed_at', models.DateTimeField(blank=True, null=True)),
                        ('cancel_requested', models.BooleanField(default=False)),
                        ('prompt_counter', models.PositiveIntegerField(default=0)),
                        ('awaiting_prompt_id', models.CharField(blank=True, max_length=64, null=True)),
                        ('awaiting_prompt_text', models.CharField(blank=True, max_length=255, null=True)),
                        ('awaiting_prompt_secret', models.BooleanField(default=False)),
                        (
                            'pending_answer_prompt_id',
                            models.CharField(blank=True, max_length=64, null=True),
                        ),
                        ('pending_answer_ciphertext', models.BinaryField(blank=True, null=True)),
                        ('pending_answer_received_at', models.DateTimeField(blank=True, null=True)),
                        ('audit_sequence', models.PositiveBigIntegerField(default=0)),
                        ('client_ip', models.CharField(blank=True, max_length=45, null=True)),
                        ('user_agent', models.TextField(blank=True, null=True)),
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
                                to='applications.app',
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
                        (
                            'service',
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name='interactive_sessions',
                                to='service_mgmt.service',
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
                                to='interactive_sessions.interactiverunsession',
                            ),
                        ),
                    ],
                    options={
                        'verbose_name': 'Interactive Run Event',
                        'verbose_name_plural': 'Interactive Run Events',
                        'db_table': 'interactive_run_events',
                    },
                ),
                migrations.CreateModel(
                    name='InteractiveRunAuditChunk',
                    fields=[
                        ('id', models.BigAutoField(primary_key=True, serialize=False)),
                        (
                            'direction',
                            models.CharField(
                                choices=[('input', 'Input'), ('output', 'Output')], max_length=12
                            ),
                        ),
                        ('sequence', models.PositiveBigIntegerField()),
                        ('size', models.PositiveIntegerField(default=0)),
                        ('content_ciphertext', models.BinaryField()),
                        ('consumed_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                        ('metadata', models.JSONField(blank=True, default=dict)),
                        ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                        (
                            'session',
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name='audit_chunks',
                                to='interactive_sessions.interactiverunsession',
                            ),
                        ),
                    ],
                    options={
                        'verbose_name': 'Interactive Run Audit Chunk',
                        'verbose_name_plural': 'Interactive Run Audit Chunks',
                        'db_table': 'interactive_run_audit_chunks',
                    },
                ),
                migrations.AddIndex(
                    model_name='interactiverunsession',
                    index=models.Index(fields=['app', 'status'], name='idx_irs_app_status'),
                ),
                migrations.AddIndex(
                    model_name='interactiverunsession',
                    index=models.Index(
                        fields=['created_by', 'created_at'], name='idx_irs_user_created'
                    ),
                ),
                migrations.AddIndex(
                    model_name='interactiverunsession',
                    index=models.Index(
                        fields=['service', 'created_at'], name='idx_irs_service_created'
                    ),
                ),
                migrations.AddIndex(
                    model_name='interactiverunsession',
                    index=models.Index(fields=['runner_id', 'status'], name='idx_irs_runner_status'),
                ),
                migrations.AddIndex(
                    model_name='interactiverunevent',
                    index=models.Index(fields=['session', 'id'], name='idx_ire_session_id'),
                ),
                migrations.AddIndex(
                    model_name='interactiverunauditchunk',
                    index=models.Index(fields=['session', 'sequence'], name='idx_ira_session_seq'),
                ),
                migrations.AddIndex(
                    model_name='interactiverunauditchunk',
                    index=models.Index(
                        fields=['session', 'direction', 'sequence'], name='idx_ira_session_dir_seq'
                    ),
                ),
                migrations.AddIndex(
                    model_name='interactiverunauditchunk',
                    index=models.Index(fields=['direction', 'consumed_at'], name='idx_ira_dir_consumed'),
                ),
                migrations.AddConstraint(
                    model_name='interactiverunauditchunk',
                    constraint=models.UniqueConstraint(
                        fields=('session', 'sequence'), name='unique_ira_session_sequence'
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
