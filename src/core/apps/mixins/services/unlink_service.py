from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.mixins.services.service_dokku import unlink_dokku_service
from core.apps.models import Service
from core.apps.service_types import get_service_runtime
from core.logs.models import AppLogManager, LogCategory


class UnlinkServiceMixin:
    """Mixin para desvincular servicos de apps."""

    @shared_task(bind=True)
    def unlink_service(self, service_id: int) -> dict:
        """
        Desvincula um servico do app e remove a URL espelhada em app.variables.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            service = Service.objects.select_related('app', 'project').get(id=service_id)
        except Service.DoesNotExist:
            return {'status': 'error', 'message': f'Servico {service_id} nao encontrado'}

        app = service.app
        if not app:
            return {'status': 'error', 'message': 'Servico nao esta vinculado a nenhum app'}

        try:
            runtime = get_service_runtime(service.service_type)
        except ValueError as exc:
            return {'status': 'error', 'message': str(exc)}

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
                meta={'current': 30, 'total': 100, 'status': 'Desvinculando servico...'},
            )

            unlink_output, unlink_command = unlink_dokku_service(
                dokku_adapter,
                runtime,
                dokku_service_name,
                app.name_dokku,
            )
            logger.dokku(
                unlink_output,
                command=unlink_command,
                category=LogCategory.DATABASE,
                progress=60,
            )

            if app.variables and isinstance(app.variables, dict) and runtime.env_key in app.variables:
                app.variables = dict(app.variables)
                del app.variables[runtime.env_key]
                app.save(update_fields=['variables'])
                logger.info(
                    f'{runtime.env_key} removida das variaveis do app',
                    category=LogCategory.CONFIG,
                    progress=80,
                )

            service.app = None
            service.save(update_fields=['app'])

            logger.success(
                f'Servico {runtime.label} desvinculado com sucesso!',
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
