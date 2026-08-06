import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: repoints SSHCommandAudit.service at service_mgmt.Service.

    No database_operations — the FK column and its target table ('services',
    unchanged by the move) are identical before and after.
    """

    dependencies = [
        ('logs', '0004_alter_applog_app_alter_sshcommandaudit_app'),
        ('service_mgmt', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='sshcommandaudit',
                    name='service',
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='ssh_command_audits',
                        to='service_mgmt.service',
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
