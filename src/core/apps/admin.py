from django.contrib import admin

from .models import App, AppProcessScale, AppRunArtifact, InteractiveRunEvent, InteractiveRunSession, Service


class ReadOnlyAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class InteractiveRunEventInline(admin.TabularInline):
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


@admin.register(App)
class AppAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at', 'updated_at')
    search_fields = ('name', 'project__name', 'domain')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'app', 'user', 'host', 'port', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('name', 'app__name', 'user', 'host')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AppProcessScale)
class AppProcessScaleAdmin(admin.ModelAdmin):
    list_display = (
        'app',
        'process_name',
        'desired_quantity',
        'current_quantity',
        'last_synced_at',
        'updated_at',
    )
    list_filter = ('process_name', 'last_synced_at', 'updated_at')
    search_fields = ('app__name', 'app__name_dokku', 'process_name')
    readonly_fields = ('detected_at', 'last_synced_at', 'updated_at')


@admin.register(AppRunArtifact)
class AppRunArtifactAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'kind', 'filename', 'app', 'created_by', 'size', 'created_at', 'expires_at')
    list_filter = ('kind', 'created_at', 'expires_at')
    search_fields = ('filename', 'app__name', 'created_by__email', 'created_by__name')
    readonly_fields = (
        'id',
        'app',
        'created_by',
        'kind',
        'filename',
        'content_type',
        'size',
        'expires_at',
        'created_at',
    )
    fields = readonly_fields


@admin.register(InteractiveRunSession)
class InteractiveRunSessionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        'id',
        'app',
        'created_by',
        'command_kind',
        'status',
        'task_id',
        'created_at',
        'last_activity_at',
        'completed_at',
    )
    list_filter = ('command_kind', 'status', 'created_at', 'completed_at')
    search_fields = ('id', 'task_id', 'app__name', 'created_by__email', 'created_by__name')
    readonly_fields = (
        'id',
        'app',
        'created_by',
        'command_kind',
        'status',
        'manage_path',
        'task_id',
        'cancel_requested',
        'prompt_counter',
        'awaiting_prompt_id',
        'awaiting_prompt_text',
        'awaiting_prompt_secret',
        'pending_answer_prompt_id',
        'pending_answer_received_at',
        'expires_at',
        'last_activity_at',
        'started_at',
        'completed_at',
        'created_at',
        'updated_at',
    )
    fields = readonly_fields
    inlines = (InteractiveRunEventInline,)


@admin.register(InteractiveRunEvent)
class InteractiveRunEventAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'session', 'event_type', 'payload_preview', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('session__id', 'session__app__name', 'session__created_by__email')
    readonly_fields = ('id', 'session', 'event_type', 'payload', 'created_at')
    fields = readonly_fields

    @admin.display(description='Payload')
    def payload_preview(self, obj):
        preview = str(obj.payload)
        return preview[:120] + ('...' if len(preview) > 120 else '')
