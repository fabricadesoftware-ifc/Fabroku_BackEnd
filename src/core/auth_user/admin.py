from django.contrib import admin

from core.auth_user.allowed_emails.admin import *  # noqa: F401, F403
from core.auth_user.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['id', 'username', 'email', 'is_active', 'is_staff', 'date_joined']
    list_filter = ['is_active', 'is_staff', 'date_joined']
    search_fields = ['username', 'email']
    ordering = ['id']
    readonly_fields = ['date_joined', 'last_login']
