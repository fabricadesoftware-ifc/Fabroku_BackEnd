from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.apps.models import App
from core.adapters import DokkuAdapter

from .models import AppLog
from .serializers import AppLogSerializer


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
        return AppLog.objects.filter(app__project__users=self.request.user).select_related('app')

    @action(detail=False, methods=['get'], url_path='stream/(?P<task_id>[^/.]+)')
    def stream(self, request, task_id=None):
        """
        Polling de logs em tempo real.
        Query params: ?after={last_id} para pegar logs novos.
        """
        queryset = self.filter_queryset(self.get_queryset().filter(task_id=task_id))

        after_id = request.query_params.get('after')
        if after_id:
            queryset = queryset.filter(id__gt=int(after_id))

        queryset = queryset.order_by('created_at')
        serializer = self.get_serializer(queryset, many=True)
        logs = serializer.data

        return Response({
            'logs': logs,
            'last_id': logs[-1]['id'] if logs else after_id,
            'count': len(logs),
            'total_in_db': self.get_queryset().filter(task_id=task_id).count(),
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

        if not request.user.is_superuser and not app.project.users.filter(id=request.user.id).exists():
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

    @action(detail=False, methods=['get'], url_path='debug')
    def debug(self, request):
        """Endpoint temporário para diagnóstico de logs ausentes."""
        task_id = request.query_params.get('task_id', '')
        all_count = AppLog.objects.filter(task_id=task_id).count()
        filtered_count = self.get_queryset().filter(task_id=task_id).count()
        sample = AppLog.objects.filter(task_id=task_id).select_related('app__project').order_by('id').first()
        return Response({
            'task_id': task_id,
            'total_in_db': all_count,
            'after_user_filter': filtered_count,
            'user': str(request.user),
            'sample': {
                'id': sample.id if sample else None,
                'app_id': sample.app_id if sample else None,
                'project_users': list(sample.app.project.users.values_list('id', flat=True)) if sample else None,
            },
        })
