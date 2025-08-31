from django.db import models
from django.utils import timezone
from core.user.infra.user_django_app.models import User
from .network import Network  


class Projeto(models.Model):
    STATUS_CHOICES = [
        ('rascunho', 'Rascunho'),
        ('em_andamento', 'Em Andamento'),
        ('pronto', 'Pronto'),
        ('abortado', 'Abortado'),
        ('erro', 'Erro'),
    ]
    
    SOURCE_TYPE_CHOICES = [
        ('git', 'Repositório Git'),
        ('docker_image', 'Imagem Docker'),
    ]

    SOURCE_TECHNOLOGY = [
        ('Vue', 'Vue.js'),
        ('Django', 'Django REST Framework')
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projetos', verbose_name="Usuário")
    name = models.CharField(max_length=200, verbose_name="Nome do Projeto")
    description = models.TextField(blank=True, verbose_name="Descrição")
    technology = models.CharField(max_length=100, choices=SOURCE_TECHNOLOGY, verbose_name="Tecnologia")
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES, verbose_name="Fonte do código")
    source_url = models.URLField(verbose_name="URL da Fonte")

    network = models.ForeignKey(Network, on_delete=models.CASCADE, related_name='projetos', verbose_name="Rede")

    port = models.IntegerField(verbose_name="Porta")
    variables = models.JSONField(blank=True, null=True, verbose_name="Variáveis de Ambiente")
    
    domain = models.CharField(max_length=100, verbose_name="Domínio do site", blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='rascunho', verbose_name="Status")
    creation_date = models.DateTimeField(default=timezone.now, verbose_name="Data de Criação")
    last_update_date = models.DateTimeField(auto_now=True, verbose_name="Última Atualização")
    url_deploy = models.URLField(blank=True, null=True, verbose_name="URL do Deploy")
    
    def save(self, *args, **kwargs):
        domain_fabrica = ".fabricadesoftware.ifc.edu.br"
        if self.name:
            if self.port:
                self.domain = f"{self.name}{domain_fabrica}:{self.port}"
            else:
                self.domain = f"{self.name}{domain_fabrica}"
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Projeto"
        verbose_name_plural = "Projetos"
        ordering = ['-last_update_date']
    
    def __str__(self):
        return f"{self.name} - {self.user.name}"