from rest_framework import serializers

from .models import AppLog


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
