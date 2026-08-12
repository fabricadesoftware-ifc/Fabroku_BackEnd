import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: repoints App.project/Service.project at projects.Project.

    No database_operations — the FK columns and their target table ('projects',
    unchanged by the move) are identical before and after; only Django's
    migration-state bookkeeping of which app owns the target model changes.
    Must apply before core/project/migrations/0003_delete_project.py removes
    Project from core.project's state (a model can't be deleted from state
    while another model still has a relation pointing at it there).
    """

    dependencies = [
        ('apps', '0024_postgis_and_service_connection_metadata'),
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='app',
                    name='project',
                    field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='projects.project'),
                ),
                migrations.AlterField(
                    model_name='service',
                    name='project',
                    field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='projects.project'),
                ),
            ],
            database_operations=[],
        ),
    ]
