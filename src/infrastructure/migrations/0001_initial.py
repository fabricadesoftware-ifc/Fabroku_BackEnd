from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: registers CacheVersionIndex under `infrastructure`.

    No database_operations — the `cache_version_indexes` table already exists,
    created by core.apps's original migrations. This just moves Django's
    bookkeeping of the model to its new app label; see
    core/apps/migrations/0030_delete_cacheversionindex.py for the matching
    removal.
    """

    initial = True

    dependencies = []

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='CacheVersionIndex',
                    fields=[
                        (
                            'id',
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                            ),
                        ),
                        ('namespace', models.CharField(db_index=True, max_length=100, unique=True)),
                        ('version', models.PositiveBigIntegerField(default=1)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        'verbose_name': 'Cache Version Index',
                        'verbose_name_plural': 'Cache Version Indexes',
                        'db_table': 'cache_version_indexes',
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
