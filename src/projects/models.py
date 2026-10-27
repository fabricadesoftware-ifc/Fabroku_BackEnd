import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from identity.models import User


class ActiveProjectManager(models.Manager):
    """Manager padrao: esconde projetos com soft delete (serializers, viewsets, admin)."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    users = models.ManyToManyField(User, related_name='projects', null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_projects',
    )

    objects = ActiveProjectManager()
    all_objects = models.Manager()

    def soft_delete(self, *, deleted_by_id: int | None = None):
        self.deleted_at = self.deleted_at or timezone.now()
        if deleted_by_id:
            self.deleted_by_id = deleted_by_id
        self.save(update_fields=['deleted_at', 'deleted_by', 'updated_at'])

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'projects'
        verbose_name = 'Project'
        verbose_name_plural = 'Projects'
        base_manager_name = 'all_objects'
