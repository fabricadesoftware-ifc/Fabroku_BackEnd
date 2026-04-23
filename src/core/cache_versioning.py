from django.db.models import F

ADMIN_STORAGE_USAGE_CACHE_NAMESPACE = 'admin-storage-usage'
ADMIN_USERS_LIST_CACHE_NAMESPACE = 'admin-users-list'


def _get_cache_version_model():
    from core.apps.models import CacheVersionIndex

    return CacheVersionIndex


def get_cache_version(namespace: str) -> int:
    cache_version_model = _get_cache_version_model()
    cache_version, _ = cache_version_model.objects.get_or_create(
        namespace=namespace,
        defaults={'version': 1},
    )
    return int(cache_version.version)


def build_versioned_cache_key(namespace: str, *, suffix: str = 'default') -> str:
    version = get_cache_version(namespace)
    return f'cache:{namespace}:v{version}:{suffix}'


def bump_cache_version(namespace: str) -> int:
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
