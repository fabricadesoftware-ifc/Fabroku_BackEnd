from django.db import models
from django.contrib.auth.models import AbstractUser
from src.core.user.infra.user_django_app.manager import CustomUserManager
from django.utils import timezone
from django.core.validators import RegexValidator

class User(AbstractUser):
    username = None
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, null=True, blank=True)
    matricula = models.CharField(
        max_length=10,
        validators=[
            RegexValidator(regex=r'^\d{10}$', message="A matrícula deve conter exatamente 10 números.")
        ],
        unique=True,
        verbose_name="Matrícula")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]
    EMAIL_FIELD = "email"
    
    objects = CustomUserManager()

    def __str__(self):
        return f"{self.name}"
    
    class Meta:
        app_label = "user_django_app"
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"

