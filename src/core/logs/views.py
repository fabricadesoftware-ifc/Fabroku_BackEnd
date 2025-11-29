from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

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
        })
