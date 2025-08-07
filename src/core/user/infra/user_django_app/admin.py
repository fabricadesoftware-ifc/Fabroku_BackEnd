from django.contrib import admin
from .models import User, Turma, Aluno

# Register your models here.
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    fields= ["name", "email"]
    list_display = ["name", "email"]

@admin.register(Turma)
class TurmaAdmin(admin.ModelAdmin):
    fields = ["turma"]
    list_display = ["turma", "codigo"]

@admin.register(Aluno)
class AlunoAdmin(admin.ModelAdmin):
    fields = ["usuario", "nome", "email", "matricula", "turma"]
    list_display = ["nome", "turma", "email"]