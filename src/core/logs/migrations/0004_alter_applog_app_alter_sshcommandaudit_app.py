import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: repoints AppLog.app/SSHCommandAudit.app at applications.App.

    No database_operations — the FK columns and their target table ('apps',
    unchanged by the move) are identical before and after; only Django's
    migration-state bookkeeping of which app owns the target model changes.
    """

    dependencies = [
        ('applications', '0001_initial'),
        ('logs', '0003_sshcommandaudit'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='applog',
                    name='app',
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='logs',
                        to='applications.app',
                    ),
                ),
                migrations.AlterField(
                    model_name='sshcommandaudit',
                    name='app',
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='ssh_command_audits',
                        to='applications.app',
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
