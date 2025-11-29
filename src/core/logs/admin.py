from django.contrib import admin

from .models import AppLog


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
