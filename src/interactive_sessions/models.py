import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from applications.models import App
from service_mgmt.models import Service


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
