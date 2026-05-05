import time
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.mixins.services.database_url import sync_database_url_from_dokku
from core.apps.models import App, Service
from core.logs.models import AppLogManager, LogCategory


def _check_dokku_output(output: str, operation: str):
    if not output:
        raise RuntimeError(f'{operation}: nenhuma resposta do servidor')
    output_lower = output.lower()
    if 'failed to execute command' in output_lower or 'ssh connection error' in output_lower:
        raise RuntimeError(f'{operation} falhou: {output}')


class LinkServiceMixin:
    """Mixin para vincular/desvincular servicos a apps."""

    @shared_task(bind=True)
    def link_service(self, service_id: int, app_id: int) -> dict:
        """
        Vincula um servico existente a um app.
        Executa postgres:link e sincroniza DATABASE_URL em app.variables.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            service: Service = Service.objects.select_related('project').get(id=service_id)
            app: App = App.objects.select_related('project').get(id=app_id)
        except Service.DoesNotExist:
            return {'status': 'error', 'message': f'Servico {service_id} nao encontrado'}
        except App.DoesNotExist:
            return {'status': 'error', 'message': f'App {app_id} nao encontrado'}

        if service.project_id != app.project_id:
            return {'status': 'error', 'message': 'Servico e app devem pertencer ao mesmo projeto'}

        if service.app_id:
            return {'status': 'error', 'message': f'Servico ja vinculado ao app {service.app_id}'}

        if not app.name_dokku:
            return {'status': 'error', 'message': 'App sem name_dokku configurado'}

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()
        dokku_service_name = service.container_name

        if not dokku_service_name:
            return {'status': 'error', 'message': 'Servico sem container_name'}

        try:
            task.update_state(
                state='PROGRESS',
                meta={'current': 20, 'total': 100, 'status': 'Vinculando banco ao app...'},
            )
            logger.info(
                f'Vinculando {dokku_service_name} ao app {app.name_dokku}...',
                category=LogCategory.DATABASE,
                progress=20,
            )

            link_output = dokku_adapter.link_database(
                db_name=dokku_service_name,
                app_name=app.name_dokku,
                no_restart=True,
            )

            logger.dokku(
                link_output,
                command=f'postgres:link {dokku_service_name} {app.name_dokku}',
                category=LogCategory.DATABASE,
                progress=50,
            )

            if 'already linked' not in link_output.lower():
                _check_dokku_output(link_output, 'postgres:link')

            task.update_state(
                state='PROGRESS',
                meta={'current': 70, 'total': 100, 'status': 'Sincronizando variaveis...'},
            )

            sync_database_url_from_dokku(
                app=app,
                dokku_adapter=dokku_adapter,
                logger=logger,
                progress=80,
            )
            service.app = app
            service.save(update_fields=['app'])

            dokku_adapter.start_database(dokku_service_name)
            time.sleep(2)

            task.update_state(
                state='PROGRESS',
                meta={'current': 90, 'total': 100, 'status': 'Reiniciando app para aplicar DATABASE_URL...'},
            )
            restart_output = dokku_adapter.restart_app(app.name_dokku)
            logger.dokku(
                restart_output,
                command=f'ps:restart {app.name_dokku}',
                category=LogCategory.DEPLOY,
                progress=90,
            )

            logger.success(
                f'Servico vinculado ao app {app.name} com sucesso!',
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
