import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0020_appprocessscale'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='app',
            name='deleted_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='app',
            name='deleted_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='deleted_apps',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='service',
            name='deleted_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='service',
            name='deleted_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='deleted_services',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='app',
            name='status',
            field=models.CharField(
                choices=[
                    ('STARTING', 'Starting'),
                    ('RUNNING', 'Running'),
                    ('STOPPED', 'Stopped'),
                    ('STOPPING', 'Stopping'),
                    ('RESTARTING', 'Restarting'),
                    ('ERROR', 'Error'),
                    ('DELETING', 'Deleting'),
                    ('DEPLOYING', 'Deploying'),
                    ('DELETED', 'Deleted'),
                ],
                default='STOPPED',
                max_length=50,
            ),
        ),
        migrations.RemoveConstraint(
            model_name='app',
            name='unique_app_name',
        ),
        migrations.AddConstraint(
            model_name='app',
            constraint=models.UniqueConstraint(
                condition=models.Q(deleted_at__isnull=True),
                fields=('name',),
                name='unique_active_app_name',
            ),
        ),
        migrations.AddConstraint(
            model_name='app',
            constraint=models.UniqueConstraint(
                condition=(
                    models.Q(deleted_at__isnull=True)
                    & models.Q(name_dokku__isnull=False)
                    & ~models.Q(name_dokku='')
                ),
                fields=('name_dokku',),
                name='unique_active_app_name_dokku',
            ),
        ),
    ]
