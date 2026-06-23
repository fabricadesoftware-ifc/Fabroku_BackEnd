from django.contrib import admin

from .models import AppLog, SSHCommandAudit


@admin.register(AppLog)
class AppLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'app', 'level', 'category', 'message_preview', 'progress', 'created_at']
    list_filter = ['level', 'category', 'app', 'created_at']
    search_fields = ['message', 'task_id', 'app__name']
    readonly_fields = ['created_at']
    ordering = ['-created_at']

    def message_preview(self, obj):
        """Exibe preview da mensagem."""
        return obj.message[:80] + '...' if len(obj.message) > 80 else obj.message  # noqa: PLR2004

    message_preview.short_description = 'Mensagem'  # type: ignore


@admin.register(SSHCommandAudit)
class SSHCommandAuditAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'created_at',
        'origin',
        'command_family',
        'status',
        'duration_ms',
        'app',
        'user',
        'request_path',
        'task_id',
    ]
    list_filter = ['status', 'origin', 'command_family', 'created_at']
    search_fields = [
        'sanitized_command',
        'command_hash',
        'app__name',
        'app__name_dokku',
        'user__email',
        'task_id',
        'request_path',
    ]
    readonly_fields = [
        'id',
        'user',
        'app',
        'service',
        'origin',
        'command_family',
        'sanitized_command',
        'command_hash',
        'status',
        'exit_status',
        'duration_ms',
        'task_id',
        'request_path',
        'request_method',
        'error_summary',
        'metadata',
        'created_at',
    ]
    fields = readonly_fields
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
