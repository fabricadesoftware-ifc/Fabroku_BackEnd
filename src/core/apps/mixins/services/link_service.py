from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.mixins.services.service_dokku import (
    check_dokku_output,
    link_dokku_service,
    sync_service_url_from_dokku,
)
from core.apps.models import App, Service
from core.apps.service_types import get_service_runtime
from core.logs.models import AppLogManager, LogCategory


def _load_service_and_app(service_id: int, app_id: int) -> tuple[Service | None, App | None, dict | None]:
    service = None
    app = None
    error = None

    try:
        service = Service.objects.select_related('project').get(id=service_id)
        app = App.objects.select_related('project').get(id=app_id)
    except Service.DoesNotExist:
        error = {'status': 'error', 'message': f'Servico {service_id} nao encontrado'}
    except App.DoesNotExist:
        error = {'status': 'error', 'message': f'App {app_id} nao encontrado'}

    if service and app:
        if service.project_id != app.project_id:
            error = {'status': 'error', 'message': 'Servico e app devem pertencer ao mesmo projeto'}
        elif service.app_id:
            error = {'status': 'error', 'message': f'Servico ja vinculado ao app {service.app_id}'}
        elif not app.name_dokku:
            error = {'status': 'error', 'message': 'App sem name_dokku configurado'}
        elif not service.container_name:
            error = {'status': 'error', 'message': 'Servico sem container_name'}

    return service, app, error


class LinkServiceMixin:
    """Mixin para vincular servicos a apps."""

    @shared_task(bind=True)
    def link_service(self, service_id: int, app_id: int) -> dict:
        """Vincula um servico existente a um app e sincroniza a URL de conexao."""
        task = cast(Task, self)
        task_id = task.request.id
        service, app, error = _load_service_and_app(service_id, app_id)
        if error:
            return error
        assert service is not None
        assert app is not None

        try:
            runtime = get_service_runtime(service.service_type)
        except ValueError as exc:
            return {'status': 'error', 'message': str(exc)}

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()
        dokku_service_name = service.container_name

        try:
            task.update_state(
                state='PROGRESS',
                meta={'current': 20, 'total': 100, 'status': 'Vinculando servico ao app...'},
            )
            logger.info(
                f'Vinculando {runtime.label} {dokku_service_name} ao app {app.name_dokku}...',
                category=LogCategory.DATABASE,
                progress=20,
            )

            link_output, link_command, link_operation = link_dokku_service(
                dokku_adapter,
                runtime,
                dokku_service_name,
                app.name_dokku,
                no_restart=True,
            )
            logger.dokku(link_output, command=link_command, category=LogCategory.DATABASE, progress=50)
            if 'already linked' not in link_output.lower():
                check_dokku_output(link_output, link_operation)

            task.update_state(
                state='PROGRESS',
                meta={'current': 70, 'total': 100, 'status': 'Sincronizando variaveis...'},
            )
            sync_service_url_from_dokku(
                app=app,
                dokku_adapter=dokku_adapter,
                logger=logger,
                runtime=runtime,
                progress=80,
            )

            service.app = app
            service.save(update_fields=['app'])

            task.update_state(
                state='PROGRESS',
                meta={'current': 90, 'total': 100, 'status': f'Reiniciando app para aplicar {runtime.env_key}...'},
            )
            restart_output = dokku_adapter.restart_app(app.name_dokku)
            logger.dokku(
                restart_output,
                command=f'ps:restart {app.name_dokku}',
                category=LogCategory.DEPLOY,
                progress=90,
            )

            logger.success(
                f'Servico {runtime.label} vinculado ao app {app.name} com sucesso!',
                category=LogCategory.DATABASE,
                progress=100,
            )

            return {
                'status': 'linked',
                'service_id': service_id,
                'app_id': app_id,
            }

        except Exception as e:
            logger.error(
                f'Erro ao vincular servico: {str(e)}',
                category=LogCategory.DATABASE,
                metadata={'error_type': type(e).__name__, 'error_details': str(e)},
            )
            raise
