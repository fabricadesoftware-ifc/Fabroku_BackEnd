
from django.db import models
from django.core.validators import RegexValidator
from django.contrib.auth.models import User
from django.conf import settings

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

class Aluno(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alunos", verbose_name="Usuário")
    nome = models.CharField(max_length=50, verbose_name="Nome completo")
    email = models.EmailField(verbose_name="Email")
    matricula = models.CharField(
        max_length=10,
        validators=[
            RegexValidator(regex=r'^\d{10}$', message="A matrícula deve conter exatamente 10 números.")
        ],
        unique=True,
        verbose_name="Matrícula")
    turma = models.ForeignKey(Turma, on_delete=models.CASCADE, related_name="alunos")

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome}, {self.turma}"