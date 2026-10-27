from rest_framework import serializers

from observability.models import AdminNotification, AppLog


class AppLogSerializer(serializers.ModelSerializer):
    """Serializer para AppLog."""

    level_display = serializers.CharField(source='get_level_display', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = AppLog
        fields = [
            'id',
            'app',
            'task_id',
            'message',
            'level',
            'level_display',
            'category',
            'category_display',
            'metadata',
            'progress',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class AppLogSummarySerializer(serializers.Serializer):
    """Serializer para resumo de logs de uma operação."""

    task_id = serializers.CharField()
    app_id = serializers.IntegerField()
    app_name = serializers.CharField()
    total_logs = serializers.IntegerField()
    current_progress = serializers.IntegerField()
    last_message = serializers.CharField()
    last_level = serializers.CharField()
    started_at = serializers.DateTimeField()
    last_update = serializers.DateTimeField()
    has_errors = serializers.BooleanField()
    is_complete = serializers.BooleanField()


class AdminNotificationSerializer(serializers.ModelSerializer):
    event_display = serializers.CharField(source='get_event_type_display', read_only=True)
    app_name = serializers.CharField(source='app.name', read_only=True, default=None)
    project_id = serializers.UUIDField(source='app.project_id', read_only=True, default=None)
    service_name = serializers.CharField(source='service.name', read_only=True, default=None)

    class Meta:
        model = AdminNotification
        fields = [
            'id',
            'event_type',
            'event_display',
            'level',
            'title',
            'message',
            'app',
            'app_name',
            'project_id',
            'service',
            'service_name',
            'metadata',
            'created_at',
            'read_at',
        ]
        read_only_fields = fields
