from dataclasses import dataclass

from core.apps.models import ServiceType


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
