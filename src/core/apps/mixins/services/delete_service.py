from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.mixins.services.service_dokku import (
    check_dokku_output,
    delete_dokku_service,
    unlink_dokku_service,
)
from core.apps.models import Service
from core.apps.service_types import get_service_runtime
from core.logs.models import AppLogManager, LogCategory


def _remove_app_env_key(app, env_key: str):
    if app.variables and isinstance(app.variables, dict) and env_key in app.variables:
        app.variables = dict(app.variables)
        del app.variables[env_key]
        app.save(update_fields=['variables'])


def _prepare_task_context(service: Service, task_id: str) -> AppLogManager | None:
    if not service.app:
        service.task_id = task_id
        service.save(update_fields=['task_id'])
        return None

    service.app.task_id = task_id
    service.app.save(update_fields=['task_id'])
    return AppLogManager(service.app, task_id)


def _unlink_remote_service_if_needed(
    task: Task,
    dokku_adapter,
    service: Service,
    runtime,
    logger: AppLogManager | None,
):
    app = service.app
    dokku_service_name = service.container_name or service.name
    if not app:
        return

    if not app.name_dokku:
        _remove_app_env_key(app, runtime.env_key)
        return

    task.update_state(
        state='PROGRESS',
        meta={'current': 20, 'total': 100, 'status': 'Desvinculando servico do app...'},
    )
    if logger:
        logger.info(
            f'Desvinculando {runtime.label} {dokku_service_name} do app {app.name_dokku}...',
            category=LogCategory.DATABASE,
            progress=20,
        )

    unlink_succeeded = False
    if dokku_service_name:
        try:
            output, command = unlink_dokku_service(dokku_adapter, runtime, dokku_service_name, app.name_dokku)
            if logger:
                logger.dokku(output, command=command, category=LogCategory.DATABASE, progress=35)
            check_dokku_output(output, f'{runtime.default_prefix}:unlink', allow_empty=True)
            unlink_succeeded = True
        except Exception as exc:
            if logger:
                logger.warning(
                    f'Unlink nao confirmado; aplicando limpeza direta de {runtime.env_key}: {str(exc)}',
                    category=LogCategory.DATABASE,
                    progress=35,
                )

    # O plugin remove a env durante o unlink, mas o unset explicito garante a
    # limpeza mesmo quando o servico ja nao existe ou o unlink falha parcialmente.
    unset_output = dokku_adapter.unset_config(
        app_name=app.name_dokku,
        keys=[runtime.env_key],
        no_restart=unlink_succeeded,
    )
    if logger:
        logger.dokku(
            unset_output,
            command=f'config:unset {app.name_dokku} {runtime.env_key}',
            category=LogCategory.CONFIG,
            progress=45,
        )
    check_dokku_output(unset_output, f'config:unset {runtime.env_key}', allow_empty=True)
    _remove_app_env_key(app, runtime.env_key)


def _delete_remote_service(task: Task, dokku_adapter, service: Service, runtime, logger: AppLogManager | None):
    dokku_service_name = service.container_name or service.name
    task.update_state(
        state='PROGRESS',
        meta={'current': 50, 'total': 100, 'status': f'Deletando servico {dokku_service_name}...'},
    )
    if logger:
        logger.info(
            f'Deletando {runtime.label} {dokku_service_name} do Dokku...',
            category=LogCategory.DATABASE,
            progress=50,
        )

    try:
        output, command = delete_dokku_service(dokku_adapter, runtime, dokku_service_name)
        if logger:
            logger.dokku(output, command=command, category=LogCategory.DATABASE, progress=80)
    except Exception as e:
        if logger:
            logger.warning(
                f'Erro ao deletar no Dokku (continuando...): {str(e)}',
                category=LogCategory.DATABASE,
                progress=80,
            )


class DeleteServiceMixin:
    """Mixin para exclusao de servicos via Celery."""

    @shared_task(bind=True)
    def delete_service(self, service_id: int, deleted_by_id: int | None = None) -> dict:
        """
        Desvincula o servico do app no Dokku, deleta o servico remoto e preserva
        o registro local como excluido.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            service = Service.objects.select_related('app', 'project').get(id=service_id)
        except Service.DoesNotExist:
            return {'status': 'deleted', 'message': 'Service already deleted'}

        if service.deleted_at:
            return {'status': 'deleted', 'message': 'Service already marked as deleted', 'service_id': service_id}

        try:
            runtime = get_service_runtime(service.service_type)
        except ValueError as exc:
            return {'status': 'error', 'message': str(exc)}

        dokku_adapter = DokkuAdapter()
        logger = _prepare_task_context(service, task_id)

        try:
            _unlink_remote_service_if_needed(task, dokku_adapter, service, runtime, logger)
            _delete_remote_service(task, dokku_adapter, service, runtime, logger)

            service.soft_delete(deleted_by_id=deleted_by_id)

            if logger:
                logger.success(
                    f'Servico {runtime.label} removido com sucesso!',
                    category=LogCategory.DATABASE,
                    progress=100,
                )

            return {
                'status': 'deleted',
                'service_id': service.id,
            }

        except Exception as e:
            if logger:
                logger.error(
                    f'Erro ao deletar servico: {str(e)}',
                    category=LogCategory.DATABASE,
                    metadata={'error_type': type(e).__name__, 'error_details': str(e)},
                )
            raise
