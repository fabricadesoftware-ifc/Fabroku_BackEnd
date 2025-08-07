from django.db import models
from django.contrib.auth.models import AbstractUser
from src.core.user.infra.user_django_app.manager import CustomUserManager
from django.utils import timezone

class Turma(models.Model):
    TURMA_CHOICES = [
        ('1info1','1info1' ),
        ('1info2','1info2' ),
        ('1info3','1info3' ),
        ('2info1','2info1' ),
        ('2info2','2info2' ),
        ('2info3','2info3' ),
        ('3info1','3info1' ),
        ('3info2','3info2' ),
        ('3info3','3info3' ),
        ('Redes1', 'Redes1'),
        ('Redes3', 'Redes3'),
        ('Redes5', 'Redes5'),
        ('BSI1', 'BSI1'),
        ('BSI3', 'BSI3'),
        ('BSI5', 'BSI5'),
        ('BSI7', 'BSI7'),
    ]
    
    turma = models.CharField(max_length=10, choices=TURMA_CHOICES, verbose_name="Turma")
    codigo = models.CharField(max_length=10, unique=True)

    def save(self, *args, **kwargs):
        ano_atual = timezone.now().year
        self.codigo = f"{ano_atual}{self.turma}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.turma}"

    class Meta:
        verbose_name = "Turma"
        verbose_name_plural = "Turmas"

class User(AbstractUser):
    username = None
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, null=True, blank=True)
    password = models.CharField(max_length=255, null=True, blank=True)
    # turma = models.ForeignKey(Turma, on_delete=models.CASCADE, related_name="Usuarios", null=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]
    EMAIL_FIELD = "email"
    
    objects = CustomUserManager()

    def __str__(self):
        return f"{self.name}"
    
    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"

