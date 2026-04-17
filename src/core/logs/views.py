from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.apps.models import App
from core.adapters import DokkuAdapter

from .models import AppLog
from .serializers import AppLogSerializer


def _has_global_access(user) -> bool:
    """Retorna True para perfis com visibilidade administrativa global."""
    return bool(getattr(user, 'is_superuser', False))


@extend_schema(tags=['logs'])
class AppLogViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para visualização de logs de aplicações."""

    queryset = AppLog.objects.all()
    serializer_class = AppLogSerializer
    filterset_fields = ['level', 'category', 'task_id', 'app', 'progress']
    search_fields = ['message', 'task_id']
    ordering_fields = ['created_at', 'level', 'progress']
    ordering = ['-created_at']

    def get_queryset(self):  # type: ignore
        """Retorna logs apenas das apps do usuário."""
        if self.request.user.is_anonymous:
            return AppLog.objects.none()
        if _has_global_access(self.request.user):
            return AppLog.objects.all().select_related('app')
        return AppLog.objects.filter(app__project__users=self.request.user).distinct().select_related('app')

    @action(detail=False, methods=['get'], url_path='stream/(?P<task_id>[^/.]+)')
    def stream(self, request, task_id=None):
        """
        Polling de logs em tempo real.
        Query params: ?after={last_id} para pegar logs novos.
        """
        base_queryset = self.get_queryset().filter(task_id=task_id)

        after_id = request.query_params.get('after')
        if after_id:
            base_queryset = base_queryset.filter(id__gt=int(after_id))

        queryset = base_queryset.order_by('created_at')
        serializer = self.get_serializer(queryset, many=True)
        logs = serializer.data

        return Response({
            'logs': logs,
            'last_id': logs[-1]['id'] if logs else after_id,
            'count': len(logs),
            'user_id': getattr(request.user, 'id', None),
            'user_email': getattr(request.user, 'email', None),
            'is_superuser': getattr(request.user, 'is_superuser', False),
            'is_anonymous': getattr(request.user, 'is_anonymous', True),
        })

    @action(detail=False, methods=['get'], url_path='app-runtime')
    def app_runtime(self, request):
        """
        Logs em tempo real do container (stdout/stderr do app).
        Query params: ?app={app_id}&num={number}.
        """
        app_id = request.query_params.get('app')
        if not app_id:
            return Response({'error': 'Parâmetro app é obrigatório'}, status=400)

        try:
            app = App.objects.select_related('project').get(id=app_id)
        except App.DoesNotExist:
            return Response({'error': 'App não encontrado'}, status=404)

        if not _has_global_access(request.user) and not app.project.users.filter(id=request.user.id).exists():
            return Response({'error': 'Sem permissão'}, status=403)

        if not app.name_dokku:
            return Response({'lines': [], 'message': 'App sem name_dokku'})

        num = min(int(request.query_params.get('num', 200)), 500)
        try:
            dokku = DokkuAdapter()
            output = dokku.logs_app(app.name_dokku, num_lines=num)
            lines = [ln.strip() for ln in (output or '').split('\n') if ln.strip()]
        except Exception as e:
            return Response({'lines': [], 'error': str(e)}, status=500)

        return Response({'lines': lines})
