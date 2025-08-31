from django.contrib import admin
from core.project.infra.project_django_app.models import Projeto

@admin.register(Projeto)
class ProjetoAdmin(admin.ModelAdmin):
    fields = ["user", "name", "description", "technology", "source_type", "port", "variables", "domain"]

    list_display =["name", "technology", "domain", "user"]