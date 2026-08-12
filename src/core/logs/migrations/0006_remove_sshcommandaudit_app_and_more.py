from django.db import migrations


class Migration(migrations.Migration):
    """State-only: removes AppLog/SSHCommandAudit from core.logs's state — they
    now live in `observability` (see observability/migrations/0001_initial.py).

    No database_operations — neither table is touched.
    """

    dependencies = [
        ('logs', '0005_alter_sshcommandaudit_service'),
        ('observability', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='sshcommandaudit',
                    name='app',
                ),
                migrations.RemoveField(
                    model_name='sshcommandaudit',
                    name='service',
                ),
                migrations.RemoveField(
                    model_name='sshcommandaudit',
                    name='user',
                ),
                migrations.DeleteModel(
                    name='AppLog',
                ),
                migrations.DeleteModel(
                    name='SSHCommandAudit',
                ),
            ],
            database_operations=[],
        ),
    ]
