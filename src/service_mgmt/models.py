from django.conf import settings
from django.db import models
from django.utils import timezone

from applications.models import App
from projects.models import Project


class ServiceType(models.TextChoices):
    POSTGRES = 'postgres', 'Postgres'
    POSTGIS = 'postgis', 'PostGIS'
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
    env_key = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    image = models.CharField(max_length=255, null=True, blank=True)
    image_version = models.CharField(max_length=100, null=True, blank=True)
    task_id = models.CharField(max_length=255, null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_services',
    )

    def soft_delete(self, *, deleted_by_id: int | None = None):
        self.deleted_at = self.deleted_at or timezone.now()
        if deleted_by_id:
            self.deleted_by_id = deleted_by_id
        self.save(update_fields=['deleted_at', 'deleted_by', 'updated_at'])

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'services'
        verbose_name = 'Service'
        verbose_name_plural = 'Services'
        constraints = [
            models.UniqueConstraint(
                fields=['app', 'env_key'],
                condition=(
                    models.Q(deleted_at__isnull=True)
                    & models.Q(app__isnull=False)
                    & models.Q(env_key__isnull=False)
                    & ~models.Q(env_key='')
                ),
                name='unique_active_service_env_key_per_app',
            ),
        ]
