from django.contrib import admin

from core.project.models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Admin para gerenciar projetos."""

    list_display = ['name', 'created_at', 'updated_at']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = [
        (
            None,
            {
                'fields': ('name', 'users'),
            },
        ),
        (
            'Datas',
            {
                'fields': ('created_at', 'updated_at'),
                'classes': ('collapse',),
            },
        ),
    ]
