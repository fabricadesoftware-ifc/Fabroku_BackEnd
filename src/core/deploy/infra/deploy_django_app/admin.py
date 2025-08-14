from django.contrib import admin
from .models import Deploy


@admin.register(Deploy)
class DeployAdmin(admin.ModelAdmin):
	list_display = ("id", "app_name", "status", "github_repo", "updated_at")
	list_filter = ("status",)
	search_fields = ("app_name", "github_repo")
