import hashlib
import re

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.apps.models import App, Service

SENSITIVE_LOG_KEYS = (
    'API_KEY',
    'BROKER_URL',
    'DATABASE_URL',
    'DSN',
    'KEY',
    'PASS',
    'PASSWORD',
    'PWD',
    'RABBITMQ_URL',
    'REDIS_URL',
    'SECRET',
    'TOKEN',
)
ENV_OUTPUT_PATTERN = re.compile(r'(?m)^(\s*[A-Za-z_][A-Za-z0-9_]*\s*:\s*)(.+)$')
ENV_ASSIGNMENT_PATTERN = re.compile(r'(?m)(\b[A-Za-z_][A-Za-z0-9_]*=)([^\s]+)')


def _is_sensitive_key(key: str) -> bool:
    normalized = key.upper()
    return any(marker in normalized for marker in SENSITIVE_LOG_KEYS)


def redact_sensitive_log_message(message: str | None) -> str | None:
    """Oculta valores sensiveis que aparecem em outputs de comandos."""
    if message is None:
        return None

    def replace_output(match: re.Match) -> str:
        prefix = match.group(1)
        key = prefix.split(':', 1)[0].strip()
        if _is_sensitive_key(key):
            return f'{prefix}[oculto]'
        return match.group(0)

    def replace_assignment(match: re.Match) -> str:
        prefix = match.group(1)
        key = prefix[:-1]
        if _is_sensitive_key(key):
            return f'{prefix}[oculto]'
        return match.group(0)

    redacted = ENV_OUTPUT_PATTERN.sub(replace_output, message)
    return ENV_ASSIGNMENT_PATTERN.sub(replace_assignment, redacted)


class LogLevel(models.TextChoices):
    """Níveis de log suportados."""

    DEBUG = 'DEBUG', 'Debug'
    INFO = 'INFO', 'Info'
    WARNING = 'WARNING', 'Warning'
    ERROR = 'ERROR', 'Error'
    SUCCESS = 'SUCCESS', 'Success'
    DOKKU = 'DOKKU', 'Dokku Output'


class LogCategory(models.TextChoices):
    """Categorias de log para filtrar por tipo de operação."""

    SYSTEM = 'SYSTEM', 'Sistema'
    CREATE = 'CREATE', 'Criação'
    DEPLOY = 'DEPLOY', 'Deploy'
    CONFIG = 'CONFIG', 'Configuração'
    GIT = 'GIT', 'Git'
    DATABASE = 'DATABASE', 'Banco de Dados'
    DOMAIN = 'DOMAIN', 'Domínio'
    SSL = 'SSL', 'SSL/TLS'


class AppLog(models.Model):
    """
    Modelo para armazenar logs de operações das aplicações.
    Cada log representa uma linha/evento durante uma operação.
    """

    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='logs')
    task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    message = models.TextField(help_text='Mensagem do log')
    level = models.CharField(max_length=20, choices=LogLevel.choices, default=LogLevel.INFO)
    category = models.CharField(max_length=20, choices=LogCategory.choices, default=LogCategory.SYSTEM)

    metadata = models.JSONField(default=dict, blank=True)

    progress = models.IntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'app_logs'
        verbose_name = 'App Log'
        verbose_name_plural = 'App Logs'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['app', 'task_id']),
            models.Index(fields=['app', 'created_at']),
        ]

    def __str__(self):
        return f'[{self.level}] {self.app.name}: {self.message[:50]}'


class SSHCommandAuditStatus(models.TextChoices):
    SUCCESS = 'success', 'Success'
    FAILED = 'failed', 'Failed'
    TIMEOUT = 'timeout', 'Timeout'
    ERROR = 'error', 'Error'


class SSHCommandAudit(models.Model):
    """Registro resumido de comandos SSH executados pelo Fabroku."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ssh_command_audits',
    )
    app = models.ForeignKey(
        App,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ssh_command_audits',
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ssh_command_audits',
    )
    origin = models.CharField(max_length=128, blank=True, default='')
    command_family = models.CharField(max_length=64, blank=True, default='', db_index=True)
    sanitized_command = models.TextField()
    command_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=SSHCommandAuditStatus.choices,
        default=SSHCommandAuditStatus.SUCCESS,
        db_index=True,
    )
    exit_status = models.IntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    request_path = models.CharField(max_length=512, blank=True, default='')
    request_method = models.CharField(max_length=16, blank=True, default='')
    error_summary = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    @staticmethod
    def hash_command(command: str) -> str:
        return hashlib.sha256(command.encode('utf-8')).hexdigest()

    def __str__(self):
        return f'{self.command_family or "ssh"}:{self.status}:{self.created_at:%Y-%m-%d %H:%M:%S}'

    class Meta:
        db_table = 'ssh_command_audits'
        verbose_name = 'SSH Command Audit'
        verbose_name_plural = 'SSH Command Audits'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at'], name='idx_ssh_audit_created'),
            models.Index(fields=['origin', 'created_at'], name='idx_ssh_audit_origin'),
            models.Index(fields=['app', 'created_at'], name='idx_ssh_audit_app'),
            models.Index(fields=['user', 'created_at'], name='idx_ssh_audit_user'),
        ]


class AppLogManager:
    """
    Gerenciador de logs para facilitar a criação de logs durante operações.
    Uso:
        logger = AppLogManager(app, task_id)
        logger.info("Iniciando deploy...", category=LogCategory.DEPLOY, progress=10)
        logger.dokku("Output do comando dokku...")
        logger.error("Falha!", metadata={"error": str(e)})
    """

    def __init__(self, app: App, task_id: str | None = None):
        self.app = app
        self.task_id = task_id

    def _log(
        self,
        message: str | None,
        level: str = LogLevel.INFO,
        category: str = LogCategory.SYSTEM,
        progress: int = 0,
        metadata: dict | None = None,
    ) -> AppLog:
        """Cria um registro de log."""
        # Garante que message nunca seja None
        if message is None:
            message = '(sem saída)'
        elif not message.strip():
            message = '(saída vazia)'

        message = redact_sensitive_log_message(message)

        return AppLog.objects.create(
            app=self.app,
            task_id=self.task_id,
            message=message,
            level=level,
            category=category,
            progress=progress,
            metadata=metadata or {},
        )

    def debug(self, message: str | None, **kwargs) -> AppLog:
        return self._log(message, level=LogLevel.DEBUG, **kwargs)

    def info(self, message: str | None, **kwargs) -> AppLog:
        return self._log(message, level=LogLevel.INFO, **kwargs)

    def warning(self, message: str | None, **kwargs) -> AppLog:
        return self._log(message, level=LogLevel.WARNING, **kwargs)

    def error(self, message: str | None, **kwargs) -> AppLog:
        return self._log(message, level=LogLevel.ERROR, **kwargs)

    def success(self, message: str | None, **kwargs) -> AppLog:
        return self._log(message, level=LogLevel.SUCCESS, **kwargs)

    def dokku(self, output: str | None, command: str = '', **kwargs) -> AppLog:
        """Log específico para output de comandos Dokku."""
        metadata = kwargs.pop('metadata', {})
        metadata['command'] = command
        return self._log(message=output, level=LogLevel.DOKKU, metadata=metadata, **kwargs)
