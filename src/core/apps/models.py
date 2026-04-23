from django.db import models

from core.project.models import Project


class AppStatus(models.TextChoices):
    STARTING = 'STARTING', 'Starting'
    RUNNING = 'RUNNING', 'Running'
    STOPPED = 'STOPPED', 'Stopped'
    STOPPING = 'STOPPING', 'Stopping'
    RESTARTING = 'RESTARTING', 'Restarting'
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
    # Campos para persistir erro crítico
    error_type = models.CharField(max_length=100, null=True, blank=True)
    error_details = models.TextField(null=True, blank=True)
    help_url = models.URLField(null=True, blank=True)
    last_commit_sha = models.CharField(max_length=40, blank=True, default='')

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'apps'
        verbose_name = 'App'
        verbose_name_plural = 'Apps'
        indexes = [
            models.Index(fields=['name'], name='idx_app_name'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['name'], name='unique_app_name'),
        ]


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
    app = models.ForeignKey(App, on_delete=models.SET_NULL, null=True, blank=True, related_name='services')
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    service_type = models.CharField(max_length=50, choices=ServiceType.choices)
    container_name = models.CharField(max_length=255, null=True, blank=True)
    task_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'services'
        verbose_name = 'Service'
        verbose_name_plural = 'Services'


class CacheVersionIndex(models.Model):
    namespace = models.CharField(max_length=100, unique=True, db_index=True)
    version = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.namespace} (v{self.version})'

    class Meta:
        db_table = 'cache_version_indexes'
        verbose_name = 'Cache Version Index'
        verbose_name_plural = 'Cache Version Indexes'
