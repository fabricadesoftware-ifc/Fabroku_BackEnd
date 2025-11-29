from django.db import models
from django.utils import timezone

from core.apps.models import App


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
        message: str,
        level: str = LogLevel.INFO,
        category: str = LogCategory.SYSTEM,
        progress: int = 0,
        metadata: dict | None = None,
    ) -> AppLog:
        """Cria um registro de log."""
        return AppLog.objects.create(
            app=self.app,
            task_id=self.task_id,
            message=message,
            level=level,
            category=category,
            progress=progress,
            metadata=metadata or {},
        )

    def debug(self, message: str, **kwargs) -> AppLog:
        return self._log(message, level=LogLevel.DEBUG, **kwargs)

    def info(self, message: str, **kwargs) -> AppLog:
        return self._log(message, level=LogLevel.INFO, **kwargs)

    def warning(self, message: str, **kwargs) -> AppLog:
        return self._log(message, level=LogLevel.WARNING, **kwargs)

    def error(self, message: str, **kwargs) -> AppLog:
        return self._log(message, level=LogLevel.ERROR, **kwargs)

    def success(self, message: str, **kwargs) -> AppLog:
        return self._log(message, level=LogLevel.SUCCESS, **kwargs)

    def dokku(self, output: str, command: str = '', **kwargs) -> AppLog:
        """Log específico para output de comandos Dokku."""
        metadata = kwargs.pop('metadata', {})
        metadata['command'] = command
        return self._log(message=output, level=LogLevel.DOKKU, metadata=metadata, **kwargs)
