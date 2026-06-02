import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

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


class InteractiveRunCommandKind(models.TextChoices):
    DJANGO_CREATESUPERUSER = 'django_createsuperuser', 'Django Createsuperuser'
    POSTGRES_CONNECT = 'postgres_connect', 'Postgres Connect'


class InteractiveRunSessionStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    RUNNING = 'running', 'Running'
    AWAITING_INPUT = 'awaiting_input', 'Awaiting Input'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'
    EXPIRED = 'expired', 'Expired'


class InteractiveRunEventType(models.TextChoices):
    STATUS = 'status', 'Status'
    OUTPUT = 'output', 'Output'
    PROMPT = 'prompt', 'Prompt'
    COMPLETE = 'complete', 'Complete'
    ERROR = 'error', 'Error'


class InteractiveRunAuditDirection(models.TextChoices):
    INPUT = 'input', 'Input'
    OUTPUT = 'output', 'Output'


class InteractiveRunSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='interactive_sessions')
    service = models.ForeignKey(
        Service,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='interactive_sessions',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='interactive_run_sessions',
    )
    command_kind = models.CharField(max_length=64, choices=InteractiveRunCommandKind.choices)
    status = models.CharField(
        max_length=32,
        choices=InteractiveRunSessionStatus.choices,
        default=InteractiveRunSessionStatus.PENDING,
    )
    manage_path = models.CharField(max_length=255, default='manage.py')
    task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    runner_id = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)
    prompt_counter = models.PositiveIntegerField(default=0)
    awaiting_prompt_id = models.CharField(max_length=64, null=True, blank=True)
    awaiting_prompt_text = models.CharField(max_length=255, null=True, blank=True)
    awaiting_prompt_secret = models.BooleanField(default=False)
    pending_answer_prompt_id = models.CharField(max_length=64, null=True, blank=True)
    pending_answer_ciphertext = models.BinaryField(null=True, blank=True)
    pending_answer_received_at = models.DateTimeField(null=True, blank=True)
    audit_sequence = models.PositiveBigIntegerField(default=0)
    client_ip = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    last_activity_at = models.DateTimeField(db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.command_kind}:{self.app.name}'

    class Meta:
        db_table = 'interactive_run_sessions'
        verbose_name = 'Interactive Run Session'
        verbose_name_plural = 'Interactive Run Sessions'
        indexes = [
            models.Index(fields=['app', 'status'], name='idx_irs_app_status'),
            models.Index(fields=['created_by', 'created_at'], name='idx_irs_user_created'),
            models.Index(fields=['service', 'created_at'], name='idx_irs_service_created'),
            models.Index(fields=['runner_id', 'status'], name='idx_irs_runner_status'),
        ]


class InteractiveRunRunner(models.Model):
    runner_id = models.CharField(max_length=128, primary_key=True)
    hostname = models.CharField(max_length=255, blank=True, default='')
    pid = models.PositiveIntegerField(default=0)
    max_sessions = models.PositiveIntegerField(default=1)
    active_sessions = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now)
    last_heartbeat_at = models.DateTimeField(db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.runner_id

    class Meta:
        db_table = 'interactive_run_runners'
        verbose_name = 'Interactive Run Runner'
        verbose_name_plural = 'Interactive Run Runners'
        indexes = [
            models.Index(fields=['last_heartbeat_at'], name='idx_irr_last_heartbeat'),
        ]


class InteractiveRunEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(InteractiveRunSession, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=32, choices=InteractiveRunEventType.choices)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f'{self.event_type}:{self.session_id}:{self.id}'

    class Meta:
        db_table = 'interactive_run_events'
        verbose_name = 'Interactive Run Event'
        verbose_name_plural = 'Interactive Run Events'
        indexes = [
            models.Index(fields=['session', 'id'], name='idx_ire_session_id'),
        ]


class InteractiveRunAuditChunk(models.Model):
    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(InteractiveRunSession, on_delete=models.CASCADE, related_name='audit_chunks')
    direction = models.CharField(max_length=12, choices=InteractiveRunAuditDirection.choices)
    sequence = models.PositiveBigIntegerField()
    size = models.PositiveIntegerField(default=0)
    content_ciphertext = models.BinaryField()
    consumed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f'{self.session_id}:{self.sequence}:{self.direction}'

    class Meta:
        db_table = 'interactive_run_audit_chunks'
        verbose_name = 'Interactive Run Audit Chunk'
        verbose_name_plural = 'Interactive Run Audit Chunks'
        constraints = [
            models.UniqueConstraint(fields=['session', 'sequence'], name='unique_ira_session_sequence'),
        ]
        indexes = [
            models.Index(fields=['session', 'sequence'], name='idx_ira_session_seq'),
            models.Index(fields=['session', 'direction', 'sequence'], name='idx_ira_session_dir_seq'),
            models.Index(fields=['direction', 'consumed_at'], name='idx_ira_dir_consumed'),
        ]
