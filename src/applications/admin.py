from django.contrib import admin
from unfold.admin import ModelAdmin

from applications.models import App, AppProcessScale, AppRunArtifact
from interactive_sessions.admin import ReadOnlyAdminMixin


@admin.register(App)
class AppAdmin(ModelAdmin):
    list_display = ('id', 'name', 'project', 'status', 'deleted_at', 'deleted_by', 'created_at', 'updated_at')
    list_filter = ('status', 'deleted_at', 'created_at', 'updated_at')
    search_fields = ('name', 'project__name', 'domain')
    readonly_fields = ('created_at', 'updated_at', 'deleted_at', 'deleted_by')


@admin.register(AppProcessScale)
class AppProcessScaleAdmin(ModelAdmin):
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
class AppRunArtifactAdmin(ReadOnlyAdminMixin, ModelAdmin):
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
