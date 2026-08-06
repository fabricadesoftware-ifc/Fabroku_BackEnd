from django.contrib import admin
from unfold.admin import ModelAdmin

from service_mgmt.models import Service


@admin.register(Service)
class ServiceAdmin(ModelAdmin):
    list_display = (
        'id',
        'name',
        'service_type',
        'app',
        'env_key',
        'image_version',
        'host',
        'port',
        'deleted_at',
        'created_at',
    )
    list_filter = ('service_type', 'deleted_at', 'created_at', 'updated_at')
    search_fields = ('name', 'app__name', 'user', 'host')
    readonly_fields = (
        'env_key',
        'image',
        'image_version',
        'created_at',
        'updated_at',
        'deleted_at',
        'deleted_by',
    )
