from django.db import models
from django.utils import timezone
from core.user.infra.user_django_app.models import User


class Projeto(models.Model):
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('concluido', 'Concluído'),
        ('em_andamento', 'Em andamento')
    ]
    
    TIPO_FONTE_CHOICES = [
        ('Docker', 'Imagem Docker'),
        ('Github', 'Repositório GitHub'),
    ]

    TIPO_TECNOLOGIA = [
        ('Vue', 'Vue.js'),
        ('Django', 'Django REST Framework')
    ]
    
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projetos')
    nome = models.CharField(max_length=200, verbose_name="Nome do Projeto")
    descricao = models.TextField(verbose_name="Descrição")
    tecnologia = models.CharField(max_length=100, choices=TIPO_TECNOLOGIA, verbose_name="Tecnologia Principal")
    tipo_fonte = models.CharField(max_length=20, choices=TIPO_FONTE_CHOICES, default='Github', verbose_name="Tipo de Fonte")
    
    # Campos para GitHub
    github_repo = models.URLField(verbose_name="URL do Repositório GitHub")
    github_branch = models.CharField(max_length=100, default='main', verbose_name="Branch do GitHub")
    github_token = models.CharField(max_length=255, blank=True, null=True, verbose_name="Token do GitHub (caso o repositório seja privado)")

    # Campos do Docker
    image_repo = models.CharField(max_length=100, verbose_name="Repositório da imagem (DockerHub)")
    image_tag = models.CharField(max_length=50, verbose_name="Tag da imagem")

    # Configurações de deploy
    porta_personalizada = models.IntegerField(blank=True, null=True, verbose_name="Porta Personalizada")
    variaveis_ambiente = models.JSONField(blank=True, null=True, verbose_name="Variáveis de Ambiente")
    
    dominio = models.CharField(max_length=100, verbose_name="Domínio do site")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    data_criacao = models.DateTimeField(default=timezone.now)
    data_ultima_atualizacao = models.DateTimeField(auto_now=True)
    url_deploy = models.URLField(blank=True, null=True, verbose_name="URL do Deploy")
    
    def save(self, *args, **kwargs):
        dominio_fabrica = ".fabricadesoftware"
        if self.porta_personalizada:
            self.dominio = f"{self.nome}{dominio_fabrica}:{self.porta_personalizada}"
        else:
            self.dominio = f"{self.nome}{dominio_fabrica}"
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Projeto"
        verbose_name_plural = "Projetos"
        ordering = ['-data_ultima_atualizacao']
    
    def __str__(self):
        return f"{self.nome} - {self.usuario.name}"
