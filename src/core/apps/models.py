from django.db import models

from core.project.models import Project


class App(models.Model):
    SATATUS_CHOICES = [
        ('running', 'Running'),
        ('stopped', 'Stopped'),
        ('error', 'Error'),
    ]
    name = models.CharField(max_length=255)
    name_dokku = models.CharField(max_length=255, null=True, blank=True)
    git = models.URLField()
    branch = models.CharField(max_length=255, default='main')
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=50, choices=SATATUS_CHOICES, default='stopped')
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


class Service(models.Model):
    service_choices = [
        ('postgres', 'Postgres'),
        ('rabbitmq', 'RabbitMQ'),
        ('redis', 'Redis'),
    ]

    name = models.CharField(max_length=255)
    user = models.CharField(max_length=255)
    password = models.CharField(max_length=255)
    host = models.CharField(max_length=255)
    port = models.IntegerField()
    app = models.ForeignKey(App, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    service_type = models.CharField(max_length=50, choices=service_choices)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'services'
        verbose_name = 'Service'
        verbose_name_plural = 'Services'
