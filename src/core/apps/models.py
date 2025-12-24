from django.db import models

from core.project.models import Project


class AppStatus(models.TextChoices):
    STARTING = 'STARTING', 'Starting'
    RUNNING = 'RUNNING', 'Running'
    STOPPED = 'STOPPED', 'Stopped'
    ERROR = 'ERROR', 'Error'
    DELETING = 'DELETING', 'Deleting'
    DEPLOYING = 'DEPLOYING', 'Deploying'


class App(models.Model):
    name = models.CharField(max_length=255)
    name_dokku = models.CharField(max_length=255, null=True, blank=True)
    git = models.URLField()
    branch = models.CharField(max_length=255, default='main')
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=50, choices=AppStatus.choices, default=AppStatus.STOPPED)
    domain = models.CharField(max_length=255, null=True, blank=True)
    port = models.IntegerField(null=True, blank=True)
    variables = models.JSONField(default=dict)
    task_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'apps'
        verbose_name = 'App'
        verbose_name_plural = 'Apps'


class ServiceType(models.TextChoices):
    POSTGRES = 'postgres', 'Postgres'
    RABBITMQ = 'rabbitmq', 'RabbitMQ'
    REDIS = 'redis', 'Redis'


class Service(models.Model):
    name = models.CharField(max_length=255)
    user = models.CharField(max_length=255, default='postgres')
    password = models.CharField(max_length=255)
    host = models.CharField(max_length=255)
    port = models.IntegerField()
    app = models.ForeignKey(App, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    service_type = models.CharField(max_length=50, choices=ServiceType.choices)
    container_name = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'services'
        verbose_name = 'Service'
        verbose_name_plural = 'Services'
