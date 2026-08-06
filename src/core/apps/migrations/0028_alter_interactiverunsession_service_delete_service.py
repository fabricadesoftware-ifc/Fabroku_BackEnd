import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: repoints InteractiveRunSession.service at service_mgmt.Service,
    then removes Service from core.apps's state — it now lives in `service_mgmt`
    (see service_mgmt/migrations/0001_initial.py).

    No database_operations: InteractiveRunSession's FK target table ('services',
    unchanged by the move) is the same before and after, and Service's own table
    isn't touched either. Depends on 0027 (Service's fields already dropped from
    core.apps's state) and logs' 0005 (SSHCommandAudit's FK already repointed) —
    a model can't be deleted from state while another model, in any app, still
    has a relation pointing at it.
    """

    dependencies = [
        ('apps', '0027_remove_service_app_remove_service_deleted_by_and_more'),
        ('logs', '0005_alter_sshcommandaudit_service'),
        ('service_mgmt', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='interactiverunsession',
                    name='service',
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='interactive_sessions',
                        to='service_mgmt.service',
                    ),
                ),
                migrations.DeleteModel(
                    name='Service',
                ),
            ],
            database_operations=[],
        ),
    ]
