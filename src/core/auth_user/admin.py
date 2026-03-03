from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from core.auth_user.allowed_emails.admin import *  # noqa: F401, F403
from core.auth_user.models import CLIToken, User


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
        (
            'Limites de Recursos',
            {
                'fields': ('custom_max_apps', 'custom_max_services'),
                'description': 'Deixe vazio para usar o padrão do perfil (aluno: 3 apps/2 serv, fábrica: 5 apps/3 serv, admin: ilimitado).',
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


@admin.register(CLIToken)
class CLITokenAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'name', 'token_short', 'created_at', 'last_used_at', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['user__email', 'user__name', 'name']
    readonly_fields = ['token', 'created_at', 'last_used_at']
    raw_id_fields = ['user']

    @admin.display(description='Token')
    def token_short(self, obj):
        return f'{obj.token[:8]}...' if obj.token else '-'
