import time

from core.apps.mixins.services.database_url import (
    sync_database_url_from_dokku,
    sync_redis_url_from_dokku,
)
from core.apps.models import App, ServiceType
from core.apps.service_types import ServiceRuntime
from core.logs.models import AppLogManager, LogCategory


def dokku_output_failed(output: str) -> bool:
    output_lower = output.lower()
    return 'failed' in output_lower or 'ssh connection error' in output_lower


def check_dokku_output(output: str, operation: str, *, allow_empty: bool = False):
    if not output and not allow_empty:
        raise RuntimeError(f'{operation}: nenhuma resposta do servidor')
    if not output:
        return
    if dokku_output_failed(output):
        raise RuntimeError(f'{operation} falhou: {output}')


def create_dokku_service(
    dokku_adapter,
    runtime: ServiceRuntime,
    service_name: str,
    password: str,
) -> tuple[str, str, str]:
    if runtime.service_type == ServiceType.POSTGRES.value:
        output = dokku_adapter.create_database(db_name=service_name, password=password)
        return output, f'postgres:create {service_name}', 'postgres:create'

    if runtime.service_type == ServiceType.REDIS.value:
        output = dokku_adapter.create_redis(service_name)
        return output, f'redis:create {service_name}', 'redis:create'

    raise ValueError(f'Tipo de servico nao suportado: {runtime.service_type}')


def link_dokku_service(
    dokku_adapter,
    runtime: ServiceRuntime,
    service_name: str,
    app_name: str,
    *,
    no_restart: bool,
) -> tuple[str, str, str]:
    restart_flag = ' --no-restart' if no_restart else ''

    if runtime.service_type == ServiceType.POSTGRES.value:
        output = dokku_adapter.link_database(db_name=service_name, app_name=app_name, no_restart=no_restart)
        return output, f'postgres:link {service_name} {app_name}{restart_flag}', 'postgres:link'

    if runtime.service_type == ServiceType.REDIS.value:
        output = dokku_adapter.link_redis(service_name=service_name, app_name=app_name, no_restart=no_restart)
        return output, f'redis:link {service_name} {app_name}{restart_flag}', 'redis:link'

    raise ValueError(f'Tipo de servico nao suportado: {runtime.service_type}')


def unlink_dokku_service(dokku_adapter, runtime: ServiceRuntime, service_name: str, app_name: str) -> tuple[str, str]:
    if runtime.service_type == ServiceType.POSTGRES.value:
        output = dokku_adapter.unlink_database(db_name=service_name, app_name=app_name)
        return output, f'postgres:unlink {service_name} {app_name}'

    if runtime.service_type == ServiceType.REDIS.value:
        output = dokku_adapter.unlink_redis(service_name=service_name, app_name=app_name)
        return output, f'redis:unlink {service_name} {app_name}'

    raise ValueError(f'Tipo de servico nao suportado: {runtime.service_type}')


def delete_dokku_service(dokku_adapter, runtime: ServiceRuntime, service_name: str) -> tuple[str, str]:
    if runtime.service_type == ServiceType.POSTGRES.value:
        dokku_adapter.remove_postgres_container(service_name)
        output = dokku_adapter.delete_database(db_name=service_name)
        return output, f'postgres:destroy {service_name} --force'

    if runtime.service_type == ServiceType.REDIS.value:
        output = dokku_adapter.delete_redis(service_name=service_name)
        return output, f'redis:destroy {service_name} --force'

    raise ValueError(f'Tipo de servico nao suportado: {runtime.service_type}')


def start_dokku_service(
    dokku_adapter,
    runtime: ServiceRuntime,
    service_name: str,
    *,
    logger: AppLogManager | None = None,
    progress: int = 82,
) -> str:
    if runtime.service_type == ServiceType.REDIS.value:
        return dokku_adapter.start_redis(service_name)

    if runtime.service_type != ServiceType.POSTGRES.value:
        raise ValueError(f'Tipo de servico nao suportado: {runtime.service_type}')

    start_output = dokku_adapter.start_database(service_name)
    if not dokku_output_failed(start_output):
        return start_output

    output_lower = start_output.lower()
    if 'sethostname' in output_lower or 'invalid argument' in output_lower:
        if logger:
            logger.info(
                'Container travado por hostname invalido, removendo...',
                category=LogCategory.DATABASE,
                progress=progress,
            )
        dokku_adapter.remove_postgres_container(service_name)
        time.sleep(2)
        return dokku_adapter.start_database(service_name)

    if 'already in use' in output_lower or 'conflict' in output_lower:
        if logger:
            logger.info(
                'Container em conflito, tentando postgres:stop antes de start...',
                category=LogCategory.DATABASE,
                progress=progress,
            )
        dokku_adapter.stop_database(service_name)
        time.sleep(2)
        return dokku_adapter.start_database(service_name)

    return start_output


def sync_service_url_from_dokku(
    *,
    app: App,
    dokku_adapter,
    logger: AppLogManager,
    runtime: ServiceRuntime,
    progress: int,
) -> str | None:
    if runtime.service_type == ServiceType.POSTGRES.value:
        return sync_database_url_from_dokku(
            app=app,
            dokku_adapter=dokku_adapter,
            logger=logger,
            progress=progress,
        )

    if runtime.service_type == ServiceType.REDIS.value:
        return sync_redis_url_from_dokku(
            app=app,
            dokku_adapter=dokku_adapter,
            logger=logger,
            progress=progress,
        )

    raise ValueError(f'Tipo de servico nao suportado: {runtime.service_type}')
