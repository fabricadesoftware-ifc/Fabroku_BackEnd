import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from projects.models import Project


class AppStatus(models.TextChoices):
    STARTING = 'STARTING', 'Starting'
    RUNNING = 'RUNNING', 'Running'
    STOPPED = 'STOPPED', 'Stopped'
    STOPPING = 'STOPPING', 'Stopping'
    RESTARTING = 'RESTARTING', 'Restarting'
    ERROR = 'ERROR', 'Error'
    DELETING = 'DELETING', 'Deleting'
    DEPLOYING = 'DEPLOYING', 'Deploying'
    DELETED = 'DELETED', 'Deleted'


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
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_apps',
    )

    def soft_delete(self, *, deleted_by_id: int | None = None):
        self.status = AppStatus.DELETED
        self.deleted_at = self.deleted_at or timezone.now()
        if deleted_by_id:
            self.deleted_by_id = deleted_by_id
        self.save(update_fields=['status', 'deleted_at', 'deleted_by', 'updated_at'])

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
            models.UniqueConstraint(
                fields=['name'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_app_name',
            ),
            models.UniqueConstraint(
                fields=['name_dokku'],
                condition=(
                    models.Q(deleted_at__isnull=True)
                    & models.Q(name_dokku__isnull=False)
                    & ~models.Q(name_dokku='')
                ),
                name='unique_active_app_name_dokku',
            ),
        ]


class AppRunArtifactKind(models.TextChoices):
    LOAD_DATA_UPLOAD = 'loaddata_upload', 'Loaddata Upload'
    DUMP_DATA_EXPORT = 'dumpdata_export', 'Dumpdata Export'


class AppRunArtifact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='run_artifacts')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='app_run_artifacts',
    )
    kind = models.CharField(max_length=32, choices=AppRunArtifactKind.choices)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, default='application/json')
    size = models.PositiveIntegerField(default=0)
    content = models.BinaryField()
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.kind}:{self.filename}'

    class Meta:
        db_table = 'app_run_artifacts'
        verbose_name = 'App Run Artifact'
        verbose_name_plural = 'App Run Artifacts'
        indexes = [
            models.Index(fields=['app', 'kind'], name='idx_run_art_app_kind'),
            models.Index(fields=['created_by', 'created_at'], name='idx_run_art_user_created'),
        ]


class AppProcessScale(models.Model):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='process_scales')
    process_name = models.CharField(max_length=64)
    desired_quantity = models.PositiveSmallIntegerField(default=0)
    current_quantity = models.PositiveSmallIntegerField(default=0)
    detected_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.app.name}:{self.process_name}={self.desired_quantity}'

    class Meta:
        db_table = 'app_process_scales'
        verbose_name = 'App Process Scale'
        verbose_name_plural = 'App Process Scales'
        constraints = [
            models.UniqueConstraint(fields=['app', 'process_name'], name='unique_app_process_scale'),
        ]
        indexes = [
            models.Index(fields=['app', 'process_name'], name='idx_app_process_name'),
        ]
