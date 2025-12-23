from django.contrib import admin

from .models import AllowedEmail


@admin.register(AllowedEmail)
class AllowedEmailAdmin(admin.ModelAdmin):
    """Admin para gerenciar emails permitidos."""

    list_display = ['email', 'name', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['email', 'name', 'notes']
    ordering = ['email']
    list_editable = ['is_active']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = [
        (
            None,
            {
                'fields': ('email', 'name', 'is_active'),
            },
        ),
        (
            'Informações Adicionais',
            {
                'fields': ('notes',),
                'classes': ('collapse',),
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
