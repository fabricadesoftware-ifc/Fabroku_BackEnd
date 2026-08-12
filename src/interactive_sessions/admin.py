from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from interactive_sessions.models import (
    InteractiveRunAuditChunk,
    InteractiveRunEvent,
    InteractiveRunRunner,
    InteractiveRunSession,
)

from .interactive_crypto import decrypt_interactive_text

AUDIT_CHUNK_PREVIEW_LENGTH = 1000
PAYLOAD_PREVIEW_LENGTH = 120


class ReadOnlyAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SuperuserOnlyAdminMixin:
    def has_module_permission(self, request):
        return bool(request.user and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)


class InteractiveRunEventInline(TabularInline):
    model = InteractiveRunEvent
    extra = 0
    can_delete = False
    fields = ('id', 'event_type', 'created_at', 'payload')
    readonly_fields = ('id', 'event_type', 'created_at', 'payload')
    ordering = ('id',)
    show_change_link = True
    verbose_name = 'Evento da sessao'
    verbose_name_plural = 'Eventos da sessao'

    def has_add_permission(self, request, obj=None):
        return False


class InteractiveRunAuditChunkInline(SuperuserOnlyAdminMixin, TabularInline):
    model = InteractiveRunAuditChunk
    extra = 0
    can_delete = False
    fields = ('id', 'sequence', 'direction', 'size', 'created_at', 'consumed_at', 'content_preview')
    readonly_fields = fields
    ordering = ('sequence',)
    verbose_name = 'Chunk de auditoria'
    verbose_name_plural = 'Chunks de auditoria'

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description='Conteudo')
    def content_preview(self, obj):
        try:
            content = decrypt_interactive_text(obj.content_ciphertext)
        except Exception:
            return '[falha ao descriptografar]'
        return content[:AUDIT_CHUNK_PREVIEW_LENGTH] + (
            '...' if len(content) > AUDIT_CHUNK_PREVIEW_LENGTH else ''
        )


@admin.register(InteractiveRunSession)
class InteractiveRunSessionAdmin(ReadOnlyAdminMixin, ModelAdmin):
    list_display = (
        'id',
        'app',
        'service',
        'created_by',
        'command_kind',
        'status',
        'task_id',
        'runner_id',
        'created_at',
        'last_activity_at',
        'completed_at',
    )
    list_filter = ('command_kind', 'status', 'created_at', 'completed_at')
    search_fields = ('id', 'task_id', 'app__name', 'created_by__email', 'created_by__name')
    readonly_fields = (
        'id',
        'app',
        'service',
        'created_by',
        'command_kind',
        'status',
        'manage_path',
        'task_id',
        'runner_id',
        'claimed_at',
        'cancel_requested',
        'prompt_counter',
        'awaiting_prompt_id',
        'awaiting_prompt_text',
        'awaiting_prompt_secret',
        'pending_answer_prompt_id',
        'pending_answer_received_at',
        'audit_sequence',
        'client_ip',
        'user_agent',
        'expires_at',
        'last_activity_at',
        'started_at',
        'completed_at',
        'created_at',
        'updated_at',
    )
    fields = readonly_fields
    inlines = (InteractiveRunEventInline, InteractiveRunAuditChunkInline)


@admin.register(InteractiveRunRunner)
class InteractiveRunRunnerAdmin(ReadOnlyAdminMixin, ModelAdmin):
    list_display = (
        'runner_id',
        'hostname',
        'pid',
        'active_sessions',
        'max_sessions',
        'last_heartbeat_at',
        'started_at',
    )
    list_filter = ('hostname', 'last_heartbeat_at', 'started_at')
    search_fields = ('runner_id', 'hostname')
    readonly_fields = (
        'runner_id',
        'hostname',
        'pid',
        'max_sessions',
        'active_sessions',
        'started_at',
        'last_heartbeat_at',
        'metadata',
    )
    fields = readonly_fields


@admin.register(InteractiveRunEvent)
class InteractiveRunEventAdmin(ReadOnlyAdminMixin, ModelAdmin):
    list_display = ('id', 'session', 'event_type', 'payload_preview', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('session__id', 'session__app__name', 'session__created_by__email')
    readonly_fields = ('id', 'session', 'event_type', 'payload', 'created_at')
    fields = readonly_fields

    @admin.display(description='Payload')
    def payload_preview(self, obj):
        preview = str(obj.payload)
        return preview[:PAYLOAD_PREVIEW_LENGTH] + ('...' if len(preview) > PAYLOAD_PREVIEW_LENGTH else '')


@admin.register(InteractiveRunAuditChunk)
class InteractiveRunAuditChunkAdmin(SuperuserOnlyAdminMixin, ReadOnlyAdminMixin, ModelAdmin):
    list_display = ('id', 'session', 'direction', 'sequence', 'size', 'created_at', 'consumed_at')
    list_filter = ('direction', 'created_at', 'consumed_at')
    search_fields = ('session__id', 'session__app__name', 'session__service__name', 'session__created_by__email')
    readonly_fields = (
        'id',
        'session',
        'direction',
        'sequence',
        'size',
        'created_at',
        'consumed_at',
        'metadata',
        'content_preview',
    )
    fields = readonly_fields
    ordering = ('session', 'sequence')

    @admin.display(description='Conteudo descriptografado')
    def content_preview(self, obj):
        try:
            return decrypt_interactive_text(obj.content_ciphertext)
        except Exception:
            return '[falha ao descriptografar]'
