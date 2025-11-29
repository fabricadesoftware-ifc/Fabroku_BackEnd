from django.contrib import admin

from .models import App, Service


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
