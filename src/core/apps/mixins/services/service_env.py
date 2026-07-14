import re

from core.apps.models import App, Service
from core.apps.service_types import ServiceRuntime, is_postgres_service_type

ENV_KEY_MAX_LENGTH = 255
ENV_KEY_INVALID_CHARS = re.compile(r'[^A-Z0-9_]+')


def allocate_attached_service_name(*, app: App, base_name: str) -> str:
    occupied = set(
        Service.objects.filter(app=app, deleted_at__isnull=True).values_list('name', flat=True)
    )
    if base_name not in occupied:
        return base_name

    suffix = 2
    candidate = f'{base_name}-{suffix}'
    while candidate in occupied:
        suffix += 1
        candidate = f'{base_name}-{suffix}'
    return candidate


def allocate_service_env_key(
    *,
    app: App,
    service_name: str,
    runtime: ServiceRuntime,
    exclude_service_id: int | None = None,
) -> str:
    """Escolhe uma variável estável e sem colisões para o vínculo."""
    queryset = Service.objects.filter(
        app=app,
        deleted_at__isnull=True,
        env_key__isnull=False,
    )
    if exclude_service_id:
        queryset = queryset.exclude(id=exclude_service_id)

    occupied = set(queryset.exclude(env_key='').values_list('env_key', flat=True))
    if runtime.env_key not in occupied:
        return runtime.env_key

    normalized_name = ENV_KEY_INVALID_CHARS.sub('_', service_name.upper()).strip('_')
    normalized_name = normalized_name or runtime.default_prefix.upper()
    base = normalized_name[:-4] if normalized_name.endswith('_URL') else normalized_name
    base = base[: ENV_KEY_MAX_LENGTH - len('_URL')]

    candidate = f'{base}_URL'
    suffix = 2
    while candidate in occupied:
        suffix_text = f'_{suffix}'
        truncated_base = base[: ENV_KEY_MAX_LENGTH - len(suffix_text) - len('_URL')]
        candidate = f'{truncated_base}{suffix_text}_URL'
        suffix += 1
    return candidate


def dokku_alias_for_env_key(env_key: str | None, runtime: ServiceRuntime) -> str | None:
    if not env_key or env_key == runtime.env_key:
        return None
    return env_key[:-4] if env_key.endswith('_URL') else env_key


def postgres_service_types() -> list[str]:
    return [service_type for service_type in ('postgres', 'postgis') if is_postgres_service_type(service_type)]
