from dataclasses import dataclass

from django.conf import settings

from service_mgmt.models import ServiceType


@dataclass(frozen=True)
class ServiceRuntime:
    """Metadata needed to provision and link a Dokku service."""

    service_type: str
    label: str
    default_prefix: str
    attached_suffix: str
    user: str
    port: int
    host_prefix: str
    env_key: str
    dokku_plugin: str
    image: str | None = None
    image_version: str | None = None
    required_extension: str | None = None


SERVICE_RUNTIMES = {
    ServiceType.POSTGRES.value: ServiceRuntime(
        service_type=ServiceType.POSTGRES.value,
        label='PostgreSQL',
        default_prefix='postgres',
        attached_suffix='db',
        user='postgres',
        port=5432,
        host_prefix='dokku-postgres-',
        env_key='DATABASE_URL',
        dokku_plugin='postgres',
    ),
    ServiceType.POSTGIS.value: ServiceRuntime(
        service_type=ServiceType.POSTGIS.value,
        label='PostGIS',
        default_prefix='postgis',
        attached_suffix='geo-db',
        user='postgres',
        port=5432,
        host_prefix='dokku-postgres-',
        env_key='DATABASE_URL',
        dokku_plugin='postgres',
        image=settings.FABROKU_POSTGIS_IMAGE,
        image_version=settings.FABROKU_POSTGIS_IMAGE_VERSION,
        required_extension='postgis',
    ),
    ServiceType.REDIS.value: ServiceRuntime(
        service_type=ServiceType.REDIS.value,
        label='Redis',
        default_prefix='redis',
        attached_suffix='redis',
        user='redis',
        port=6379,
        host_prefix='dokku-redis-',
        env_key='REDIS_URL',
        dokku_plugin='redis',
    ),
}


def normalize_service_type(service_type: str | ServiceType) -> str:
    return getattr(service_type, 'value', service_type)


def get_service_runtime(service_type: str | ServiceType) -> ServiceRuntime:
    normalized_type = normalize_service_type(service_type)
    runtime = SERVICE_RUNTIMES.get(normalized_type)
    if not runtime:
        supported = ', '.join(runtime.label for runtime in SERVICE_RUNTIMES.values())
        raise ValueError(f'Tipo de servico nao suportado. Suportados: {supported}.')
    return runtime


def is_supported_service_type(service_type: str | ServiceType | None) -> bool:
    if not service_type:
        return False
    return normalize_service_type(service_type) in SERVICE_RUNTIMES


def is_postgres_runtime(runtime: ServiceRuntime) -> bool:
    return runtime.dokku_plugin == 'postgres'


def is_postgres_service_type(service_type: str | ServiceType | None) -> bool:
    if not service_type:
        return False
    try:
        return is_postgres_runtime(get_service_runtime(service_type))
    except ValueError:
        return False
