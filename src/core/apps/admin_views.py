"""Views administrativas (apenas superusers)."""

from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.adapters import DokkuAdapter
from core.apps.models import App, Service
from core.cache_versioning import (
    ADMIN_STORAGE_USAGE_CACHE_NAMESPACE,
    build_versioned_cache_key,
    get_cache_ttl,
)


def _format_size(bytes_val: int) -> str:
    """Formata bytes em formato legivel (KB, MB, GB)."""
    if bytes_val is None or bytes_val < 0:
        return '-'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if bytes_val < 1024:
            return f'{bytes_val:.1f} {unit}'
        bytes_val /= 1024
    return f'{bytes_val:.1f} PB'

def _storage_usage_max_workers(total_services: int) -> int:
    configured = max(1, int(getattr(settings, 'ADMIN_STORAGE_USAGE_MAX_WORKERS', 6)))
    return max(1, min(configured, max(total_services, 1)))


def _resolve_service_storage(service: Service, apps_by_name_dokku: dict, apps_by_name: dict) -> dict:
    dokku = DokkuAdapter()

    size_bytes = dokku.get_database_size(service.container_name)
    app_id = service.app_id
    app_name = service.app.name if service.app else None

    if not app_name and service.container_name:
        try:
            links_output = dokku.app_links_for_service(service.container_name)
            linked_app = links_output.strip().splitlines()[0].strip() if links_output else ''
        except Exception:
            linked_app = ''

        if (
            linked_app
            and 'Failed to execute' not in linked_app
            and 'SSH Connection Error' not in linked_app
        ):
            app_name = linked_app
            matching_app = apps_by_name_dokku.get(linked_app) or apps_by_name.get(linked_app)
            if matching_app:
                app_id = matching_app.id

    return {
        'service_id': service.id,
        'service_name': service.name,
        'container_name': service.container_name,
        'project_id': str(service.project_id) if service.project_id else None,
        'project_name': service.project.name if service.project_id else '-',
        'app_id': app_id,
        'app_name': app_name,
        'size_bytes': size_bytes,
        'size_formatted': _format_size(size_bytes) if size_bytes is not None else '-',
    }


@extend_schema(tags=['admin'])
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def storage_usage(request):
    """
    Retorna o uso de espaco dos bancos Postgres por projeto/servico.
    Apenas superusers.
    """
    if not request.user.is_superuser:
        return Response({'error': 'Sem permissao'}, status=403)

    force_refresh = request.query_params.get('refresh') in {'1', 'true', 'True'}
    cache_ttl = get_cache_ttl(ADMIN_STORAGE_USAGE_CACHE_NAMESPACE)
    cache_key = build_versioned_cache_key(ADMIN_STORAGE_USAGE_CACHE_NAMESPACE)

    if cache_ttl and not force_refresh:
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            return Response(cached_payload)

    services = list(
        Service.objects.filter(
            service_type='postgres',
            container_name__isnull=False,
        )
        .exclude(container_name='')
        .select_related('project', 'app')
    )

    apps = list(App.objects.only('id', 'name', 'name_dokku'))
    apps_by_name_dokku = {app.name_dokku: app for app in apps if app.name_dokku}
    apps_by_name = {app.name: app for app in apps}

    max_workers = _storage_usage_max_workers(len(services))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(
            executor.map(
                lambda service: _resolve_service_storage(service, apps_by_name_dokku, apps_by_name),
                services,
            )
        )

    total_bytes = sum(result['size_bytes'] for result in results if result['size_bytes'] is not None)
    payload = {
        'services': results,
        'total_bytes': total_bytes,
        'total_formatted': _format_size(total_bytes),
    }

    if cache_ttl:
        cache.set(cache_key, payload, cache_ttl)

    return Response(payload)
