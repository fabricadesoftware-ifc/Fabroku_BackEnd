from django.db import migrations


class Migration(migrations.Migration):
    """State-only: drops Service's fields from core.apps's state ahead of deleting
    the model itself in the next migration (0028) — mirrors exactly what
    `makemigrations` proposed on its own; splitting field removal from model
    deletion is Django's own autodetector output, not a hand invention.

    No database_operations — Service's table isn't touched.
    """

    dependencies = [
        ('apps', '0026_alter_service_app_remove_apprunartifact_app_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='service',
                    name='app',
                ),
                migrations.RemoveField(
                    model_name='service',
                    name='deleted_by',
                ),
                migrations.RemoveField(
                    model_name='service',
                    name='project',
                ),
            ],
            database_operations=[],
        ),
    ]
