from django.db import models
from django.contrib.auth.models import AbstractUser
from src.core.user.infra.user_django_app.manager import CustomUserManager


class User(AbstractUser):
    username = None
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, null=True, blank=True)
    password = models.CharField(max_length=255, null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]
    EMAIL_FIELD = "email"
    
    objects = CustomUserManager()

    def __str__(self):
        return f"{self.id} - {self.name}"
    
    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"