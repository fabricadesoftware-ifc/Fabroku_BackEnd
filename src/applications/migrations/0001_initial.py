import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: registers App, AppProcessScale, AppRunArtifact under `applications`.

    No database_operations — the `apps`, `app_process_scales`, and `app_run_artifacts`
    tables (and all their indexes/constraints) already exist, created by core.apps's
    original migrations. This just moves Django's bookkeeping of these three models
    to their new app label; see core/logs/migrations/0004_... and
    core/apps/migrations/0026_... for the matching state fixes required on the other
    side of the move (models that still reference App but aren't moving with it).
    """

    initial = True

    dependencies = [
        ('projects', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='App',
                    fields=[
                        (
                            'id',
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                            ),
                        ),
                        ('name', models.CharField(max_length=255)),
                        ('name_dokku', models.CharField(blank=True, max_length=255, null=True)),
                        ('git', models.URLField()),
                        ('branch', models.CharField(default='main', max_length=255)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                        (
                            'status',
                            models.CharField(
                                choices=[
                                    ('STARTING', 'Starting'),
                                    ('RUNNING', 'Running'),
                                    ('STOPPED', 'Stopped'),
                                    ('STOPPING', 'Stopping'),
                                    ('RESTARTING', 'Restarting'),
                                    ('ERROR', 'Error'),
                                    ('DELETING', 'Deleting'),
                                    ('DEPLOYING', 'Deploying'),
                                    ('DELETED', 'Deleted'),
                                ],
                                default='STOPPED',
                                max_length=50,
                            ),
                        ),
                        ('domain', models.CharField(blank=True, max_length=255, null=True)),
                        ('port', models.IntegerField(blank=True, null=True)),
                        ('variables', models.JSONField(default=dict)),
                        ('task_id', models.CharField(blank=True, max_length=255, null=True)),
                        ('error_type', models.CharField(blank=True, max_length=100, null=True)),
                        ('error_details', models.TextField(blank=True, null=True)),
                        ('help_url', models.URLField(blank=True, null=True)),
                        ('last_commit_sha', models.CharField(blank=True, default='', max_length=40)),
                        ('deleted_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                        (
                            'deleted_by',
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name='deleted_apps',
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            'project',
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE, to='projects.project'
                            ),
                        ),
                    ],
                    options={
                        'verbose_name': 'App',
                        'verbose_name_plural': 'Apps',
                        'db_table': 'apps',
                    },
                ),
                migrations.CreateModel(
                    name='AppProcessScale',
                    fields=[
                        (
                            'id',
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                            ),
                        ),
                        ('process_name', models.CharField(max_length=64)),
                        ('desired_quantity', models.PositiveSmallIntegerField(default=0)),
                        ('current_quantity', models.PositiveSmallIntegerField(default=0)),
                        ('detected_at', models.DateTimeField(auto_now_add=True)),
                        ('last_synced_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                        (
                            'app',
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name='process_scales',
                                to='applications.app',
                            ),
                        ),
                    ],
                    options={
                        'verbose_name': 'App Process Scale',
                        'verbose_name_plural': 'App Process Scales',
                        'db_table': 'app_process_scales',
                    },
                ),
                migrations.CreateModel(
                    name='AppRunArtifact',
                    fields=[
                        (
                            'id',
                            models.UUIDField(
                                default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                            ),
                        ),
                        (
                            'kind',
                            models.CharField(
                                choices=[
                                    ('loaddata_upload', 'Loaddata Upload'),
                                    ('dumpdata_export', 'Dumpdata Export'),
                                ],
                                max_length=32,
                            ),
                        ),
                        ('filename', models.CharField(max_length=255)),
                        ('content_type', models.CharField(default='application/json', max_length=100)),
                        ('size', models.PositiveIntegerField(default=0)),
                        ('content', models.BinaryField()),
                        ('expires_at', models.DateTimeField(db_index=True)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        (
                            'app',
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name='run_artifacts',
                                to='applications.app',
                            ),
                        ),
                        (
                            'created_by',
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name='app_run_artifacts',
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        'verbose_name': 'App Run Artifact',
                        'verbose_name_plural': 'App Run Artifacts',
                        'db_table': 'app_run_artifacts',
                    },
                ),
                migrations.AddIndex(
                    model_name='app',
                    index=models.Index(fields=['name'], name='idx_app_name'),
                ),
                migrations.AddConstraint(
                    model_name='app',
                    constraint=models.UniqueConstraint(
                        condition=models.Q(('deleted_at__isnull', True)),
                        fields=('name',),
                        name='unique_active_app_name',
                    ),
                ),
                migrations.AddConstraint(
                    model_name='app',
                    constraint=models.UniqueConstraint(
                        condition=models.Q(
                            ('deleted_at__isnull', True),
                            ('name_dokku__isnull', False),
                            models.Q(('name_dokku', ''), _negated=True),
                        ),
                        fields=('name_dokku',),
                        name='unique_active_app_name_dokku',
                    ),
                ),
                migrations.AddIndex(
                    model_name='appprocessscale',
                    index=models.Index(fields=['app', 'process_name'], name='idx_app_process_name'),
                ),
                migrations.AddConstraint(
                    model_name='appprocessscale',
                    constraint=models.UniqueConstraint(
                        fields=('app', 'process_name'), name='unique_app_process_scale'
                    ),
                ),
                migrations.AddIndex(
                    model_name='apprunartifact',
                    index=models.Index(fields=['app', 'kind'], name='idx_run_art_app_kind'),
                ),
                migrations.AddIndex(
                    model_name='apprunartifact',
                    index=models.Index(
                        fields=['created_by', 'created_at'], name='idx_run_art_user_created'
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
