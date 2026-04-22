"""Views administrativas (apenas superusers)."""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.adapters import DokkuAdapter
from core.apps.models import Service


def _format_size(bytes_val: int) -> str:
    """Formata bytes em formato legível (KB, MB, GB)."""
    if bytes_val is None or bytes_val < 0:
        return '-'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if bytes_val < 1024:
            return f'{bytes_val:.1f} {unit}'
        bytes_val /= 1024
    return f'{bytes_val:.1f} PB'


@extend_schema(tags=['admin'])
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def storage_usage(request):
    """
    Retorna o uso de espaço dos bancos Postgres por projeto/serviço.
    Apenas superusers.
    """
    if not request.user.is_superuser:
        return Response({'error': 'Sem permissão'}, status=403)

    services = (
        Service.objects.filter(
            service_type='postgres',
            container_name__isnull=False,
        )
        .exclude(container_name='')
        .select_related('project', 'app')
    )

    dokku = DokkuAdapter()
    results = []
    total_bytes = 0

    # Pré-carregar apps do banco para resolver nomes via Dokku links
    from core.apps.models import App

    apps = list(App.objects.only('id', 'name', 'name_dokku'))
    apps_by_name_dokku = {app.name_dokku: app for app in apps if app.name_dokku}
    apps_by_name = {app.name: app for app in apps}
    app_name_cache: dict[str, str] = {}

    for svc in services:
        size_bytes = dokku.get_database_size(svc.container_name)
        if size_bytes is not None:
            total_bytes += size_bytes

        project_name = svc.project.name if svc.project else '-'

        # Resolver nome do app: primeiro tenta o FK, senão consulta Dokku
        app_id = svc.app_id
        app_name = None
        if svc.app:
            app_name = svc.app.name
        elif svc.container_name:
            # Consulta links do Dokku para descobrir o app vinculado
            cache_key = svc.container_name
            if cache_key not in app_name_cache:
                try:
                    links_output = dokku.app_links_for_service(svc.container_name)
                    linked_app = links_output.strip().split('\n')[0].strip() if links_output else ''
                    if (
                        linked_app
                        and 'Failed to execute' not in linked_app
                        and 'SSH Connection Error' not in linked_app
                    ):
                        app_name_cache[cache_key] = linked_app
                    else:
                        app_name_cache[cache_key] = ''
                except Exception:
                    app_name_cache[cache_key] = ''
            resolved = app_name_cache.get(cache_key, '')
            if resolved:
                app_name = resolved
                matching_app = apps_by_name_dokku.get(resolved) or apps_by_name.get(resolved)
                if matching_app:
                    app_id = matching_app.id

        results.append({
            'service_id': svc.id,
            'service_name': svc.name,
            'container_name': svc.container_name,
            'project_id': str(svc.project_id) if svc.project_id else None,
            'project_name': project_name,
            'app_id': app_id,
            'app_name': app_name,
            'size_bytes': size_bytes,
            'size_formatted': _format_size(size_bytes) if size_bytes is not None else '-',
        })

    return Response({
        'services': results,
        'total_bytes': total_bytes,
        'total_formatted': _format_size(total_bytes),
    })
