import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: registers Project under the `projects` app.

    No database_operations — the `projects` table (and its `projects_users`
    M2M through-table) already exist, created by core/project's original
    migrations. This just moves Django's bookkeeping of the model to its new
    app label; see core/apps/migrations/0025_... and
    core/project/migrations/0003_delete_project.py for the matching state
    fixes required on the other side of the move.
    """

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Project',
                    fields=[
                        (
                            'id',
                            models.UUIDField(
                                default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                            ),
                        ),
                        ('name', models.CharField(max_length=255)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                        (
                            'users',
                            models.ManyToManyField(related_name='projects', to=settings.AUTH_USER_MODEL),
                        ),
                    ],
                    options={
                        'verbose_name': 'Project',
                        'verbose_name_plural': 'Projects',
                        'db_table': 'projects',
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
