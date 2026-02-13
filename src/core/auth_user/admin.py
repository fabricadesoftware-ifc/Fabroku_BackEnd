from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from core.auth_user.allowed_emails.admin import *  # noqa: F401, F403
from core.auth_user.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin customizado para o modelo User sem senha obrigatória."""

    list_display = ['id', 'email', 'name', 'is_active', 'is_staff', 'is_superuser', 'is_fabric', 'date_joined']
    list_filter = ['is_active', 'is_staff', 'is_superuser', 'is_fabric', 'date_joined']
    search_fields = ['email', 'name']
    ordering = ['id']
    readonly_fields = ['date_joined', 'last_login']

    # Remove username dos campos (não usamos)
    ordering = ['email']
    list_display_links = ['id', 'email']

    # Fieldsets para edição (sem senha obrigatória)
    fieldsets = (
        (None, {'fields': ('email', 'name')}),
        ('Informações Pessoais', {'fields': ('avatar_url', 'git_token')}),
        (
            'Permissões',
            {
                'fields': ('is_active', 'is_staff', 'is_superuser', 'is_fabric', 'groups', 'user_permissions'),
            },
        ),
        ('Datas', {'fields': ('last_login', 'date_joined')}),
    )

    # Fieldsets para criação de novo usuário (sem senha)
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'name', 'is_active', 'is_staff', 'is_superuser', 'is_fabric'),
            },
        ),
    )
