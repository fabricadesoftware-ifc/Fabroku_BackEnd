from django.db import models
from django.utils import timezone
from core.user.infra.user_django_app.models import User
from .network import Network  # Importar o novo modelo Network


class Projeto(models.Model):
    STATUS_CHOICES = [
        ('rascunho', 'Rascunho'),
        ('em_andamento', 'Em Andamento'),
        ('pronto', 'Pronto'),
        ('abortado', 'Abortado'),
        ('erro', 'Erro'),
    ]
    
    TIPO_FONTE_CHOICES = [
        ('git', 'Repositório Git'),
        ('docker_image', 'Imagem Docker'),
    ]

    TIPO_TECNOLOGIA = [
        ('Vue', 'Vue.js'),
        ('Django', 'Django REST Framework')
    ]
    
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projetos', verbose_name="Usuário")
    nome = models.CharField(max_length=200, verbose_name="Nome do Projeto")
    descricao = models.TextField(blank=True, verbose_name="Descrição") # Descrição pode ser opcional
    tecnologia = models.CharField(max_length=100, choices=TIPO_TECNOLOGIA, verbose_name="Tecnologia Principal")
    source_type = models.CharField(max_length=20, choices=TIPO_FONTE_CHOICES, verbose_name="Tipo de Fonte")
    source_url = models.URLField(verbose_name="URL da Fonte")

    # Nova chave estrangeira para Network
    network = models.ForeignKey(Network, on_delete=models.CASCADE, related_name='projetos', verbose_name="Rede")

    porta = models.IntegerField(verbose_name="Porta") # Agora é obrigatório
    variaveis_ambiente = models.JSONField(blank=True, null=True, verbose_name="Variáveis de Ambiente")
    
    dominio = models.CharField(max_length=100, verbose_name="Domínio do site", blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='rascunho', verbose_name="Status")
    data_criacao = models.DateTimeField(default=timezone.now, verbose_name="Data de Criação")
    data_ultima_atualizacao = models.DateTimeField(auto_now=True, verbose_name="Última Atualização")
    url_deploy = models.URLField(blank=True, null=True, verbose_name="URL do Deploy")
    
    def save(self, *args, **kwargs):
        dominio_fabrica = ".fabricadesoftware.ifc.edu.br"
        if self.nome:
            if self.porta:
                self.dominio = f"{self.nome}{dominio_fabrica}:{self.porta}"
            else:
                self.dominio = f"{self.nome}{dominio_fabrica}"
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Projeto"
        verbose_name_plural = "Projetos"
        ordering = ['-data_ultima_atualizacao']
    
    def __str__(self):
        return f"{self.nome} - {self.usuario.name}"