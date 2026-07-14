from django.db import migrations, models
from django.db.models import Q

DATABASE_SERVICE_TYPES = {'postgres', 'postgis'}


def backfill_service_env_keys(apps, schema_editor):
    Service = apps.get_model('apps', 'Service')

    services = list(
        Service.objects.filter(app__isnull=False, deleted_at__isnull=True)
        .select_related('app')
        .order_by('app_id', 'created_at', 'id')
    )
    occupied_by_app: dict[int, set[str]] = {}
    family_counts: dict[tuple[int, str], int] = {}

    for service in services:
        if service.service_type in DATABASE_SERVICE_TYPES:
            family = 'database'
        elif service.service_type == 'redis':
            family = 'redis'
        else:
            continue
        key = (service.app_id, family)
        family_counts[key] = family_counts.get(key, 0) + 1

    for service in services:
        app_variables = service.app.variables if isinstance(service.app.variables, dict) else {}
        occupied = occupied_by_app.setdefault(service.app_id, set())
        matched_key = None

        connection_marker = service.host or ''
        if not connection_marker and service.container_name:
            connection_marker = f'dokku-postgres-{service.container_name}'

        for key, value in app_variables.items():
            if key in occupied or not isinstance(value, str):
                continue
            if connection_marker and connection_marker in value:
                matched_key = key
                break

        default_key = None
        if service.service_type in DATABASE_SERVICE_TYPES:
            default_key = 'DATABASE_URL'
        elif service.service_type == 'redis':
            default_key = 'REDIS_URL'

        if not matched_key and default_key and default_key not in occupied:
            family = 'database' if default_key == 'DATABASE_URL' else 'redis'
            family_count = family_counts.get((service.app_id, family), 0)
            if family_count == 1:
                matched_key = default_key

        if matched_key:
            service.env_key = matched_key
            service.save(update_fields=['env_key'])
            occupied.add(matched_key)


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0023_interactive_runner'),
    ]

    operations = [
        migrations.AlterField(
            model_name='service',
            name='service_type',
            field=models.CharField(
                choices=[
                    ('postgres', 'Postgres'),
                    ('postgis', 'PostGIS'),
                    ('rabbitmq', 'RabbitMQ'),
                    ('redis', 'Redis'),
                ],
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name='service',
            name='env_key',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='service',
            name='image',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='service',
            name='image_version',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.RunPython(backfill_service_env_keys, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='service',
            constraint=models.UniqueConstraint(
                condition=(
                    Q(deleted_at__isnull=True)
                    & Q(app__isnull=False)
                    & Q(env_key__isnull=False)
                    & ~Q(env_key='')
                ),
                fields=('app', 'env_key'),
                name='unique_active_service_env_key_per_app',
            ),
        ),
    ]
