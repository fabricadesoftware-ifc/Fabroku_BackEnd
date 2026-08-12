from django.db import migrations


class Migration(migrations.Migration):
    """State-only: removes InteractiveRunRunner/Session/Event/AuditChunk from
    core.apps's state — they now live in `interactive_sessions` (see
    interactive_sessions/migrations/0001_initial.py). Field removals ahead of
    the model deletions mirror exactly what `makemigrations` proposed on its
    own (same pattern as Service's move in 0027/0028).

    No database_operations — none of these tables are touched.
    """

    dependencies = [
        ('apps', '0028_alter_interactiverunsession_service_delete_service'),
        ('interactive_sessions', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='interactiverunauditchunk',
                    name='session',
                ),
                migrations.RemoveField(
                    model_name='interactiverunevent',
                    name='session',
                ),
                migrations.DeleteModel(
                    name='InteractiveRunRunner',
                ),
                migrations.RemoveField(
                    model_name='interactiverunsession',
                    name='app',
                ),
                migrations.RemoveField(
                    model_name='interactiverunsession',
                    name='created_by',
                ),
                migrations.RemoveField(
                    model_name='interactiverunsession',
                    name='service',
                ),
                migrations.DeleteModel(
                    name='InteractiveRunAuditChunk',
                ),
                migrations.DeleteModel(
                    name='InteractiveRunEvent',
                ),
                migrations.DeleteModel(
                    name='InteractiveRunSession',
                ),
            ],
            database_operations=[],
        ),
    ]
