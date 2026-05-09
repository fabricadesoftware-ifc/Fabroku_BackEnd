from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.mixins.services.service_dokku import delete_dokku_service, unlink_dokku_service
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
    if not app or not app.name_dokku or not dokku_service_name:
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

    try:
        output, command = unlink_dokku_service(dokku_adapter, runtime, dokku_service_name, app.name_dokku)
        if logger:
            logger.dokku(output, command=command, category=LogCategory.DATABASE, progress=40)
        _remove_app_env_key(app, runtime.env_key)
    except Exception as e:
        if logger:
            logger.warning(
                f'Erro ao desvincular (pode ja estar desvinculado): {str(e)}',
                category=LogCategory.DATABASE,
                progress=40,
            )


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
    def delete_service(self, service_id: int) -> dict:
        """
        Desvincula o servico do app no Dokku, deleta o servico remoto e remove
        o registro do banco local.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            service = Service.objects.select_related('app', 'project').get(id=service_id)
        except Service.DoesNotExist:
            return {'status': 'deleted', 'message': 'Service already deleted'}

        try:
            runtime = get_service_runtime(service.service_type)
        except ValueError as exc:
            return {'status': 'error', 'message': str(exc)}

        dokku_adapter = DokkuAdapter()
        logger = _prepare_task_context(service, task_id)

        try:
            _unlink_remote_service_if_needed(task, dokku_adapter, service, runtime, logger)
            _delete_remote_service(task, dokku_adapter, service, runtime, logger)

            service_id_saved = service.id
            service.delete()

            if logger:
                logger.success(
                    f'Servico {runtime.label} removido com sucesso!',
                    category=LogCategory.DATABASE,
                    progress=100,
                )

            return {
                'status': 'deleted',
                'service_id': service_id_saved,
            }

        except Exception as e:
            if logger:
                logger.error(
                    f'Erro ao deletar servico: {str(e)}',
                    category=LogCategory.DATABASE,
                    metadata={'error_type': type(e).__name__, 'error_details': str(e)},
                )
            raise
