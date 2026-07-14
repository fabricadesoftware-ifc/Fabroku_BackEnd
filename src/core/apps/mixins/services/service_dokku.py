import time

from core.apps.mixins.services.database_url import (
    sync_config_url_from_dokku,
)
from core.apps.mixins.services.service_env import dokku_alias_for_env_key, postgres_service_types
from core.apps.models import App, Service
from core.apps.service_types import ServiceRuntime, is_postgres_runtime
from core.logs.models import AppLogManager, LogCategory


def dokku_output_failed(output: str) -> bool:
    output_lower = output.lower()
    return any(
        marker in output_lower
        for marker in ('failed', 'ssh connection error', 'ssh command timeout')
    )


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
    if is_postgres_runtime(runtime):
        output = dokku_adapter.create_database(
            db_name=service_name,
            password=password,
            image=runtime.image,
            image_version=runtime.image_version,
        )
        image_flags = ''
        if runtime.image:
            image_flags += f' --image {runtime.image}'
        if runtime.image_version:
            image_flags += f' --image-version {runtime.image_version}'
        return output, f'postgres:create {service_name}{image_flags}', 'postgres:create'

    if runtime.dokku_plugin == 'redis':
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
    env_key: str | None = None,
) -> tuple[str, str, str]:
    restart_flag = ' --no-restart' if no_restart else ''

    if is_postgres_runtime(runtime):
        alias = dokku_alias_for_env_key(env_key, runtime)
        link_kwargs = {
            'db_name': service_name,
            'app_name': app_name,
            'no_restart': no_restart,
        }
        if alias:
            link_kwargs['alias'] = alias
        output = dokku_adapter.link_database(**link_kwargs)
        alias_flag = f' --alias {alias}' if alias else ''
        return output, f'postgres:link {service_name} {app_name}{restart_flag}{alias_flag}', 'postgres:link'

    if runtime.dokku_plugin == 'redis':
        alias = dokku_alias_for_env_key(env_key, runtime)
        link_kwargs = {
            'service_name': service_name,
            'app_name': app_name,
            'no_restart': no_restart,
        }
        if alias:
            link_kwargs['alias'] = alias
        output = dokku_adapter.link_redis(**link_kwargs)
        alias_flag = f' --alias {alias}' if alias else ''
        return output, f'redis:link {service_name} {app_name}{restart_flag}{alias_flag}', 'redis:link'

    raise ValueError(f'Tipo de servico nao suportado: {runtime.service_type}')


def unlink_dokku_service(dokku_adapter, runtime: ServiceRuntime, service_name: str, app_name: str) -> tuple[str, str]:
    if is_postgres_runtime(runtime):
        output = dokku_adapter.unlink_database(db_name=service_name, app_name=app_name)
        return output, f'postgres:unlink {service_name} {app_name}'

    if runtime.dokku_plugin == 'redis':
        output = dokku_adapter.unlink_redis(service_name=service_name, app_name=app_name)
        return output, f'redis:unlink {service_name} {app_name}'

    raise ValueError(f'Tipo de servico nao suportado: {runtime.service_type}')


def delete_dokku_service(dokku_adapter, runtime: ServiceRuntime, service_name: str) -> tuple[str, str]:
    if is_postgres_runtime(runtime):
        dokku_adapter.remove_postgres_container(service_name)
        output = dokku_adapter.delete_database(db_name=service_name)
        return output, f'postgres:destroy {service_name} --force'

    if runtime.dokku_plugin == 'redis':
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
    if runtime.dokku_plugin == 'redis':
        return dokku_adapter.start_redis(service_name)

    if not is_postgres_runtime(runtime):
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
    env_key: str | None,
    progress: int,
) -> str | None:
    return sync_config_url_from_dokku(
        app=app,
        dokku_adapter=dokku_adapter,
        logger=logger,
        config_key=env_key or runtime.env_key,
        progress=progress,
    )


def initialize_dokku_service(dokku_adapter, runtime: ServiceRuntime, service_name: str) -> tuple[str, str] | None:
    if runtime.required_extension != 'postgis':
        return None

    output = dokku_adapter.enable_postgis(service_name)
    if dokku_output_failed(output) or 'postgis_version' not in output.lower():
        raise RuntimeError(f'PostGIS nao foi habilitado corretamente: {output}')
    return output, f'postgres:connect {service_name} (habilitar PostGIS)'


def promote_remaining_database_if_needed(
    *,
    app: App,
    removed_env_key: str | None,
    excluded_service_id: int,
    dokku_adapter,
    logger: AppLogManager | None,
    progress: int,
) -> Service | None:
    if removed_env_key != 'DATABASE_URL' or not app.name_dokku:
        return None

    candidate = (
        Service.objects.filter(
            app=app,
            service_type__in=postgres_service_types(),
            deleted_at__isnull=True,
            container_name__isnull=False,
        )
        .exclude(id=excluded_service_id)
        .exclude(container_name='')
        .order_by('created_at', 'id')
        .first()
    )
    if not candidate:
        return None

    previous_env_key = candidate.env_key
    current_database_url = dokku_adapter.get_config(app.name_dokku, 'DATABASE_URL').strip()
    candidate_markers = tuple(
        marker
        for marker in (
            candidate.host,
            candidate.container_name,
            f'dokku-postgres-{candidate.container_name}',
        )
        if marker
    )
    already_promoted = bool(current_database_url) and any(
        marker in current_database_url for marker in candidate_markers
    )

    if not already_promoted:
        output = dokku_adapter.promote_database(candidate.container_name, app.name_dokku)
        if logger:
            logger.dokku(
                output,
                command=f'postgres:promote {candidate.container_name} {app.name_dokku}',
                category=LogCategory.DATABASE,
                progress=progress,
            )
        check_dokku_output(output, 'postgres:promote', allow_empty=True)

    candidate.env_key = 'DATABASE_URL'
    candidate.save(update_fields=['env_key'])

    if previous_env_key and previous_env_key != 'DATABASE_URL':
        app.variables = dict(app.variables or {})
        app.variables.pop(previous_env_key, None)
        app.save(update_fields=['variables'])

    if logger:
        sync_config_url_from_dokku(
            app=app,
            dokku_adapter=dokku_adapter,
            logger=logger,
            config_key='DATABASE_URL',
            progress=progress,
        )
        logger.info(
            f'{candidate.name} promovido para DATABASE_URL.',
            category=LogCategory.CONFIG,
            progress=progress,
        )
    return candidate
