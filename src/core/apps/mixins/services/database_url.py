import time
from typing import Protocol

from core.apps.models import App
from core.logs.models import AppLogManager, LogCategory


class ServiceConfigAdapter(Protocol):
    def get_config(self, app_name: str, key: str) -> str:
        ...


INVALID_CONFIG_URL_MARKERS = (
    'failed',
    'ssh connection error',
    'failed to execute command',
    'not found',
    'no such app',
)


def is_valid_config_url(value: str | None) -> bool:
    """Retorna True quando o config:get trouxe uma URL aproveitavel."""
    if not value:
        return False

    normalized = value.strip()
    if not normalized:
        return False

    output_lower = normalized.lower()
    if any(marker in output_lower for marker in INVALID_CONFIG_URL_MARKERS):
        return False

    return '://' in normalized


def sync_config_url_from_dokku(
    *,
    app: App,
    dokku_adapter: ServiceConfigAdapter,
    logger: AppLogManager,
    config_key: str,
    progress: int,
    attempts: int = 5,
    delay_seconds: float = 1,
) -> str | None:
    """
    Le uma URL de servico do Dokku e espelha em app.variables.

    O link do servico pode demorar um instante ate refletir em config:get. Por isso
    fazemos algumas tentativas curtas antes de desistir com log de suporte.
    """
    if not app.name_dokku:
        logger.warning(
            f'Nao foi possivel sincronizar {config_key}: app sem nome Dokku.',
            category=LogCategory.CONFIG,
            progress=progress,
        )
        return None

    last_output = ''
    for attempt in range(1, attempts + 1):
        config_value = dokku_adapter.get_config(app.name_dokku, config_key).strip()

        if is_valid_config_url(config_value):
            app.variables = dict(app.variables or {})
            app.variables[config_key] = config_value
            app.save(update_fields=['variables'])
            logger.info(
                f'{config_key} sincronizada nas variaveis do app.',
                category=LogCategory.CONFIG,
                progress=progress,
                metadata={'attempt': attempt},
            )
            return config_value

        last_output = config_value
        if attempt < attempts:
            time.sleep(delay_seconds)

    logger.warning(
        f'{config_key} nao foi retornada pelo Dokku apos o vinculo do servico.',
        category=LogCategory.CONFIG,
        progress=progress,
        metadata={'attempts': attempts, 'last_output': last_output[:160]},
    )
    return None


def sync_database_url_from_dokku(
    *,
    app: App,
    dokku_adapter: ServiceConfigAdapter,
    logger: AppLogManager,
    progress: int,
    attempts: int = 5,
    delay_seconds: float = 1,
) -> str | None:
    return sync_config_url_from_dokku(
        app=app,
        dokku_adapter=dokku_adapter,
        logger=logger,
        config_key='DATABASE_URL',
        progress=progress,
        attempts=attempts,
        delay_seconds=delay_seconds,
    )


def sync_redis_url_from_dokku(
    *,
    app: App,
    dokku_adapter: ServiceConfigAdapter,
    logger: AppLogManager,
    progress: int,
    attempts: int = 5,
    delay_seconds: float = 1,
) -> str | None:
    return sync_config_url_from_dokku(
        app=app,
        dokku_adapter=dokku_adapter,
        logger=logger,
        config_key='REDIS_URL',
        progress=progress,
        attempts=attempts,
        delay_seconds=delay_seconds,
    )
