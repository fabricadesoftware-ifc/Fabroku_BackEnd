from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from observability.models import AdminNotification

from .serializers import AdminNotificationSerializer


class IsSuperuser(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


@extend_schema(tags=['admin'])
class AdminNotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """Alertas para superusers. `?unread=1` filtra so as nao lidas."""

    serializer_class = AdminNotificationSerializer
    permission_classes = [IsSuperuser]

    def get_queryset(self):
        queryset = AdminNotification.objects.select_related('app', 'service')
        if self.request.query_params.get('unread') in {'1', 'true', 'True'}:
            queryset = queryset.filter(read_at__isnull=True)
        return queryset

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        return Response({'count': AdminNotification.objects.filter(read_at__isnull=True).count()})

    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        notification = self.get_object()
        if not notification.read_at:
            notification.read_at = timezone.now()
            notification.read_by = request.user
            notification.save(update_fields=['read_at', 'read_by'])
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=['post'])
    def read_all(self, request):
        updated = AdminNotification.objects.filter(read_at__isnull=True).update(
            read_at=timezone.now(), read_by=request.user
        )
        return Response({'updated': updated})
