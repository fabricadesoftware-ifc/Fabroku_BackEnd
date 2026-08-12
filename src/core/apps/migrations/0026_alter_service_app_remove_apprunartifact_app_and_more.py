import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: repoints Service.app/InteractiveRunSession.app at applications.App,
    then removes App/AppProcessScale/AppRunArtifact from core.apps's state — they now
    live in `applications` (see applications/migrations/0001_initial.py).

    No database_operations anywhere in this migration: none of the physical tables
    change (Service/InteractiveRunSession's FK target table, 'apps', is unchanged by
    the move; App/AppProcessScale/AppRunArtifact's own tables aren't touched either).
    Depends on core/logs' 0004 migration re-pointing AppLog/SSHCommandAudit's FKs
    first: a model can't be deleted from state while another model — in any app —
    still has a relation pointing at it.
    """

    dependencies = [
        ('applications', '0001_initial'),
        ('apps', '0025_alter_app_project_alter_service_project'),
        ('logs', '0004_alter_applog_app_alter_sshcommandaudit_app'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='service',
                    name='app',
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='services',
                        to='applications.app',
                    ),
                ),
                migrations.RemoveField(
                    model_name='apprunartifact',
                    name='app',
                ),
                migrations.AlterField(
                    model_name='interactiverunsession',
                    name='app',
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='interactive_sessions',
                        to='applications.app',
                    ),
                ),
                migrations.RemoveField(
                    model_name='appprocessscale',
                    name='app',
                ),
                migrations.RemoveField(
                    model_name='apprunartifact',
                    name='created_by',
                ),
                migrations.DeleteModel(
                    name='App',
                ),
                migrations.DeleteModel(
                    name='AppProcessScale',
                ),
                migrations.DeleteModel(
                    name='AppRunArtifact',
                ),
            ],
            database_operations=[],
        ),
    ]
