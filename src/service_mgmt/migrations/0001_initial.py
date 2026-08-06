import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: registers Service under `service_mgmt`.

    No database_operations — the `services` table (and its indexes/constraints)
    already exists, created by core.apps's original migrations. This just moves
    Django's bookkeeping of the model to its new app label; see
    core/logs/migrations/0005_... and core/apps/migrations/0027_.../0028_... for
    the matching state fixes required on the other side of the move.
    """

    initial = True

    dependencies = [
        ('applications', '0001_initial'),
        ('projects', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Service',
                    fields=[
                        (
                            'id',
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                            ),
                        ),
                        ('name', models.CharField(max_length=255)),
                        ('user', models.CharField(default='postgres', max_length=255)),
                        ('password', models.CharField(max_length=255)),
                        ('host', models.CharField(max_length=255)),
                        ('port', models.IntegerField()),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                        (
                            'service_type',
                            models.CharField(
                                choices=[
                                    ('postgres', 'Postgres'),
                                    ('postgis', 'PostGIS'),
                                    ('rabbitmq', 'RabbitMQ'),
                                    ('redis', 'Redis'),
                                ],
                                max_length=50,
                            ),
                        ),
                        ('container_name', models.CharField(blank=True, max_length=255, null=True)),
                        ('env_key', models.CharField(blank=True, db_index=True, max_length=255, null=True)),
                        ('image', models.CharField(blank=True, max_length=255, null=True)),
                        ('image_version', models.CharField(blank=True, max_length=100, null=True)),
                        ('task_id', models.CharField(blank=True, max_length=255, null=True)),
                        ('deleted_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                        (
                            'app',
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name='services',
                                to='applications.app',
                            ),
                        ),
                        (
                            'deleted_by',
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name='deleted_services',
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
                        'verbose_name': 'Service',
                        'verbose_name_plural': 'Services',
                        'db_table': 'services',
                        'constraints': [
                            models.UniqueConstraint(
                                condition=models.Q(
                                    ('deleted_at__isnull', True),
                                    ('app__isnull', False),
                                    ('env_key__isnull', False),
                                    models.Q(('env_key', ''), _negated=True),
                                ),
                                fields=('app', 'env_key'),
                                name='unique_active_service_env_key_per_app',
                            )
                        ],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
