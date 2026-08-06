from django.db import migrations


class Migration(migrations.Migration):
    """State-only: removes CacheVersionIndex from core.apps's state — it now
    lives in `infrastructure` (see infrastructure/migrations/0001_initial.py).

    No database_operations — the table isn't touched. This is the last model
    core.apps ever held; core.apps still hosts non-model code (views, mixins,
    admin, tasks) after this.
    """

    dependencies = [
        ('apps', '0029_remove_interactiverunauditchunk_session_and_more'),
        ('infrastructure', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name='CacheVersionIndex',
                ),
            ],
            database_operations=[],
        ),
    ]
