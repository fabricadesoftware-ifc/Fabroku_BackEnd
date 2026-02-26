import time
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App, Service, ServiceType
from core.logs.models import AppLogManager, LogCategory


def _check_dokku_output(output: str, operation: str):
    if not output:
        raise RuntimeError(f'{operation}: nenhuma resposta do servidor')
    output_lower = output.lower()
    if 'failed to execute command' in output_lower or 'ssh connection error' in output_lower:
        raise RuntimeError(f'{operation} falhou: {output}')


class LinkServiceMixin:
    """Mixin para vincular/desvincular serviços a apps."""

    @shared_task(bind=True)
    def link_service(self, service_id: int, app_id: int) -> dict:
        """
        Vincula um serviço existente a um app.
        Executa postgres:link, sincroniza DATABASE_URL em app.variables.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            service = Service.objects.select_related('project').get(id=service_id)
            app = App.objects.select_related('project').get(id=app_id)
        except Service.DoesNotExist:
            return {'status': 'error', 'message': f'Serviço {service_id} não encontrado'}
        except App.DoesNotExist:
            return {'status': 'error', 'message': f'App {app_id} não encontrado'}

        if service.project_id != app.project_id:
            return {'status': 'error', 'message': 'Serviço e app devem pertencer ao mesmo projeto'}

        if service.app_id:
            return {'status': 'error', 'message': f'Serviço já vinculado ao app {service.app_id}'}

        if not app.name_dokku:
            return {'status': 'error', 'message': 'App sem name_dokku configurado'}

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()
        dokku_service_name = service.container_name

        if not dokku_service_name:
            return {'status': 'error', 'message': 'Serviço sem container_name'}

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
                db_name=dokku_service_name, app_name=app.name_dokku, no_restart=False,
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
                meta={'current': 70, 'total': 100, 'status': 'Sincronizando variáveis...'},
            )

            database_url = dokku_adapter.get_config(app.name_dokku, 'DATABASE_URL')
            if database_url and 'failed' not in database_url.lower():
                app.variables = dict(app.variables or {})
                app.variables['DATABASE_URL'] = database_url
                app.save(update_fields=['variables'])
                logger.info(
                    'DATABASE_URL adicionada às variáveis do app',
                    category=LogCategory.CONFIG,
                    progress=80,
                )

            service.app = app
            service.save(update_fields=['app'])

            dokku_adapter.start_database(dokku_service_name)
            time.sleep(2)

            logger.success(
                f'Serviço vinculado ao app {app.name} com sucesso!',
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
                f'Erro ao vincular serviço: {str(e)}',
                category=LogCategory.DATABASE,
                metadata={'error_type': type(e).__name__, 'error_details': str(e)},
            )
            raise
