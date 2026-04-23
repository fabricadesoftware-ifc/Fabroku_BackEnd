from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App, Service, ServiceType
from core.logs.models import AppLogManager, LogCategory


class UnlinkServiceMixin:
    """Mixin para desvincular serviços de apps."""

    @shared_task(bind=True)
    def unlink_service(self, service_id: int) -> dict:
        """
        Desvincula um serviço do app.
        Executa postgres:unlink, remove DATABASE_URL de app.variables.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            service = Service.objects.select_related('app', 'project').get(id=service_id)
        except Service.DoesNotExist:
            return {'status': 'error', 'message': f'Serviço {service_id} não encontrado'}

        app = service.app
        if not app:
            return {'status': 'error', 'message': 'Serviço não está vinculado a nenhum app'}

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()
        dokku_service_name = service.container_name

        if not dokku_service_name or not app.name_dokku:
            service.app = None
            service.save(update_fields=['app'])
            return {'status': 'unlinked', 'service_id': service_id}

        try:
            task.update_state(
                state='PROGRESS',
                meta={'current': 30, 'total': 100, 'status': 'Desvinculando...'},
            )

            unlink_output = dokku_adapter.unlink_database(
                db_name=dokku_service_name, app_name=app.name_dokku,
            )
            logger.dokku(
                unlink_output,
                command=f'postgres:unlink {dokku_service_name} {app.name_dokku}',
                category=LogCategory.DATABASE,
                progress=60,
            )

            if app.variables and isinstance(app.variables, dict) and 'DATABASE_URL' in app.variables:
                app.variables = dict(app.variables)
                del app.variables['DATABASE_URL']
                app.save(update_fields=['variables'])
                logger.info(
                    'DATABASE_URL removida das variáveis do app',
                    category=LogCategory.CONFIG,
                    progress=80,
                )

            service.app = None
            service.save(update_fields=['app'])

            logger.success(
                'Serviço desvinculado com sucesso!',
                category=LogCategory.DATABASE,
                progress=100,
            )

            return {'status': 'unlinked', 'service_id': service_id}

        except Exception as e:
            logger.error(
                f'Erro ao desvincular: {str(e)}',
                category=LogCategory.DATABASE,
                metadata={'error_type': type(e).__name__, 'error_details': str(e)},
            )
            raise
