from django.db import migrations


class Migration(migrations.Migration):
    """State-only: removes Project from core.project's state — it now lives in
    `projects` (see projects/migrations/0001_initial.py). No database_operations:
    the `projects` table isn't touched, just Django's bookkeeping of which app
    owns it. Depends on core/apps' 0025 migration re-pointing App/Service's FKs
    first, since a model can't be deleted from state while another model still
    has a relation pointing at it here.
    """

    dependencies = [
        ('apps', '0025_alter_app_project_alter_service_project'),
        ('project', '0002_alter_project_options_remove_project_user_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name='Project',
                ),
            ],
            database_operations=[],
        ),
    ]
