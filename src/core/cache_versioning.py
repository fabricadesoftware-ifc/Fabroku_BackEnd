import os

from django.conf import settings
from django.db.models import F

ADMIN_STORAGE_USAGE_CACHE_NAMESPACE = 'admin-storage-usage'
ADMIN_USERS_LIST_CACHE_NAMESPACE = 'admin-users-list'
APP_LAST_COMMIT_CACHE_NAMESPACE = 'app-last-commit'


def _normalize_namespace(namespace: str) -> str:
    return namespace.strip().lower()


def _coerce_non_negative_int(raw_value, fallback: int) -> int:
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        return fallback


def _cache_ttl_env_key(namespace: str) -> str:
    normalized_namespace = _normalize_namespace(namespace)
    return f"CACHE_TTL_{normalized_namespace.upper().replace('-', '_')}"


def get_cache_ttl(namespace: str, *, default: int | None = None) -> int:
    normalized_namespace = _normalize_namespace(namespace)
    default_ttl = _coerce_non_negative_int(getattr(settings, 'CACHE_TTL_DEFAULT', 60), 60)
    effective_default_ttl = _coerce_non_negative_int(default, default_ttl)
    return _coerce_non_negative_int(os.getenv(_cache_ttl_env_key(normalized_namespace)), effective_default_ttl)


def _get_cache_version_model():
    from core.apps.models import CacheVersionIndex

    return CacheVersionIndex


def get_cache_version(namespace: str) -> int:
    namespace = _normalize_namespace(namespace)
    cache_version_model = _get_cache_version_model()
    cache_version, _ = cache_version_model.objects.get_or_create(
        namespace=namespace,
        defaults={'version': 1},
    )
    return int(cache_version.version)


def build_versioned_cache_key(namespace: str, *, suffix: str = 'default') -> str:
    namespace = _normalize_namespace(namespace)
    version = get_cache_version(namespace)
    return f'cache:{namespace}:v{version}:{suffix}'


def bump_cache_version(namespace: str) -> int:
    namespace = _normalize_namespace(namespace)
    cache_version_model = _get_cache_version_model()
    cache_version, created = cache_version_model.objects.get_or_create(
        namespace=namespace,
        defaults={'version': 2},
    )

    if created:
        return int(cache_version.version)

    cache_version_model.objects.filter(pk=cache_version.pk).update(version=F('version') + 1)
    cache_version.refresh_from_db(fields=['version'])
    return int(cache_version.version)
