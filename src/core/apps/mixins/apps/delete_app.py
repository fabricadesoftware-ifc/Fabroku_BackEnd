from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.mixins.services.service_dokku import delete_dokku_service, dokku_output_failed, unlink_dokku_service
from core.apps.models import App, Service
from core.apps.service_types import get_service_runtime
from core.logs.models import AppLogManager, LogCategory


def _delete_linked_service(
    *,
    dokku_adapter: DokkuAdapter,
    logger: AppLogManager,
    dokku_app_name: str | None,
    service: Service,
    progress: int,
):
    dokku_service_name = service.container_name or service.name

    try:
        runtime = get_service_runtime(service.service_type)
    except ValueError:
        service.delete()
        return

    if dokku_app_name:
        try:
            unlink_output, _command = unlink_dokku_service(dokku_adapter, runtime, dokku_service_name, dokku_app_name)
            if dokku_output_failed(unlink_output):
                logger.warning(
                    f'Unlink do servico {dokku_service_name} retornou erro: {unlink_output}',
                    category=LogCategory.DATABASE,
                    progress=progress,
                )
            else:
                logger.info(
                    f'Servico {dokku_service_name} desvinculado do app',
                    category=LogCategory.DATABASE,
                    progress=progress,
                )
        except Exception as e:
            logger.warning(
                f'Erro ao desvincular servico {dokku_service_name}: {e}',
                category=LogCategory.DATABASE,
                progress=progress,
            )

    try:
        delete_output, _command = delete_dokku_service(dokku_adapter, runtime, dokku_service_name)
        if dokku_output_failed(delete_output):
            logger.warning(
                f'Delecao do servico {dokku_service_name} retornou erro: {delete_output}',
                category=LogCategory.DATABASE,
                progress=progress,
            )
        else:
            logger.success(
                f'Servico {dokku_service_name} removido do Dokku',
                category=LogCategory.DATABASE,
                progress=progress,
            )
    except Exception as e:
        logger.warning(
            f'Erro ao deletar servico {dokku_service_name}: {e}',
            category=LogCategory.DATABASE,
            progress=progress,
        )

    service.delete()


class DeleteAppMixin:
    """Mixin para exclusao de aplicacoes via Celery."""

    @shared_task(bind=True)
    def delete_app(self, app_id: int) -> dict:
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id)
        except App.DoesNotExist:
            return {'status': 'deleted', 'message': 'App already deleted from DB'}

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()
        dokku_app_name = app.name_dokku

        task.update_state(
            state='PROGRESS',
            meta={'current': 5, 'total': 100, 'status': f'Removendo {app.name}...'},
        )
        logger.info(f'Iniciando remocao da aplicacao {app.name}...', category=LogCategory.DEPLOY, progress=5)

        services = Service.objects.filter(app=app)
        total_services = services.count()
        for idx, service in enumerate(services):
            dokku_service_name = service.container_name or service.name
            progress = 10 + int((idx / max(total_services, 1)) * 40)
            task.update_state(
                state='PROGRESS',
                meta={'current': progress, 'total': 100, 'status': f'Removendo servico {dokku_service_name}...'},
            )
            _delete_linked_service(
                dokku_adapter=dokku_adapter,
                logger=logger,
                dokku_app_name=dokku_app_name,
                service=service,
                progress=progress,
            )

        if dokku_app_name:
            task.update_state(
                state='PROGRESS',
                meta={'current': 60, 'total': 100, 'status': f'Removendo container {dokku_app_name}...'},
            )
            logger.info(
                f'Removendo app {dokku_app_name} do Dokku...',
                category=LogCategory.DEPLOY,
                progress=60,
            )

            try:
                result = dokku_adapter.delete_app(app_name=dokku_app_name)
                if dokku_output_failed(result):
                    logger.warning(
                        f'Delecao do app retornou erro: {result}',
                        category=LogCategory.DEPLOY,
                        progress=80,
                    )
                else:
                    logger.dokku(result, category=LogCategory.DEPLOY, progress=80)
            except Exception as e:
                logger.warning(
                    f'Erro ao deletar app no Dokku: {e}',
                    category=LogCategory.DEPLOY,
                    progress=80,
                )

        app.delete()
        logger.success(
            f'Aplicacao {app.name} removida com sucesso!',
            category=LogCategory.DEPLOY,
            progress=100,
        )

        return {'status': 'deleted', 'app_id': app_id, 'dokku_app': dokku_app_name}
