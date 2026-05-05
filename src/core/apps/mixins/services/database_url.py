import time
from typing import Protocol

from core.apps.models import App
from core.logs.models import AppLogManager, LogCategory


class DatabaseUrlConfigAdapter(Protocol):
    def get_config(self, app_name: str, key: str) -> str:
        ...


INVALID_DATABASE_URL_MARKERS = (
    'failed',
    'ssh connection error',
    'failed to execute command',
    'not found',
    'no such app',
)


def is_valid_database_url(value: str | None) -> bool:
    """Retorna True quando o config:get trouxe uma DATABASE_URL aproveitavel."""
    if not value:
        return False

    normalized = value.strip()
    if not normalized:
        return False

    output_lower = normalized.lower()
    if any(marker in output_lower for marker in INVALID_DATABASE_URL_MARKERS):
        return False

    return '://' in normalized


def sync_database_url_from_dokku(
    *,
    app: App,
    dokku_adapter: DatabaseUrlConfigAdapter,
    logger: AppLogManager,
    progress: int,
    attempts: int = 5,
    delay_seconds: float = 1,
) -> str | None:
    """
    Le a DATABASE_URL do Dokku e espelha em app.variables.

    O postgres:link pode demorar um instante ate refletir em config:get. Por isso
    fazemos algumas tentativas curtas antes de desistir com log de suporte.
    """
    if not app.name_dokku:
        logger.warning(
            'Nao foi possivel sincronizar DATABASE_URL: app sem nome Dokku.',
            category=LogCategory.CONFIG,
            progress=progress,
        )
        return None

    last_output = ''
    for attempt in range(1, attempts + 1):
        database_url = dokku_adapter.get_config(app.name_dokku, 'DATABASE_URL').strip()

        if is_valid_database_url(database_url):
            app.variables = dict(app.variables or {})
            app.variables['DATABASE_URL'] = database_url
            app.save(update_fields=['variables'])
            logger.info(
                'DATABASE_URL sincronizada nas variaveis do app.',
                category=LogCategory.CONFIG,
                progress=progress,
                metadata={'attempt': attempt},
            )
            return database_url

        last_output = database_url
        if attempt < attempts:
            time.sleep(delay_seconds)

    logger.warning(
        'DATABASE_URL nao foi retornada pelo Dokku apos o vinculo do banco.',
        category=LogCategory.CONFIG,
        progress=progress,
        metadata={'attempts': attempts, 'last_output': last_output[:160]},
    )
    return None
