from django.contrib import admin
from core.project.infra.project_django_app.models import Projeto

@admin.register(Projeto)
class ProjetoAdmin(admin.ModelAdmin):
    fields = ["usuario", "nome", "descricao", "tecnologia", "tipo_fonte", "porta_personalizada", "variaveis_ambiente", "dominio"]

    list_display =["nome", "tecnologia", "dominio", "usuario"]