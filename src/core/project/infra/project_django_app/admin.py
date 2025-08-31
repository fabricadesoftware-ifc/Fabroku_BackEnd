from django.contrib import admin
from core.project.infra.project_django_app.models import Project, Network

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    fields = ["user", "name", "description", "technology", "source_type", "source_git", "source_docker","network","port", "variables", "domain"]

    list_display =["name", "technology", "domain", "user"]

@admin.register(Network)
class NetworkAdmin(admin.ModelAdmin):
    fields = ["name", "description"]

    list_display = ["name"]