from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App
from core.apps.process_scale import (
    dokku_scale_output_failed,
    save_desired_process_quantities,
    sync_app_process_scales_from_dokku,
    validate_process_quantities,
)
from core.logs.models import AppLogManager, LogCategory


class ProcessScaleMixin:
    """Mixin para gerenciar escala de processos persistentes do Dokku."""

    @shared_task(bind=True)
    def scale_app_processes(self, app_id: int, processes: dict) -> dict:
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id, deleted_at__isnull=True)
        except App.DoesNotExist:
            return {'status': 'error', 'message': f'App {app_id} not found'}

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        logger.info('Aplicando escala de processos...', category=LogCategory.DEPLOY, progress=10)

        if not app.name_dokku:
            logger.error('App nao tem name_dokku configurado', category=LogCategory.DEPLOY)
            raise RuntimeError('App nao tem name_dokku configurado.')

        validated_processes = validate_process_quantities(processes)
        command = 'dokku ps:scale ' + app.name_dokku + ' ' + ' '.join(
            f'{process_name}={quantity}' for process_name, quantity in validated_processes.items()
        )

        task.update_state(
            state='PROGRESS',
            meta={'current': 35, 'total': 100, 'status': 'Executando dokku ps:scale...'},
        )

        dokku_adapter = DokkuAdapter()
        output = dokku_adapter.ps_scale(app.name_dokku, validated_processes)
        logger.dokku(output, command=command, category=LogCategory.DEPLOY, progress=75)

        if dokku_scale_output_failed(output):
            logger.error('Falha ao aplicar escala de processos.', category=LogCategory.DEPLOY, progress=100)
            raise RuntimeError(output)

        save_desired_process_quantities(app, validated_processes)
        sync_app_process_scales_from_dokku(app, dokku_adapter, output=output)

        logger.success('Escala de processos aplicada com sucesso.', category=LogCategory.DEPLOY, progress=100)

        return {
            'status': 'success',
            'message': 'Escala de processos aplicada com sucesso.',
            'app_id': app_id,
            'dokku_app': app.name_dokku,
            'processes': validated_processes,
            'output': output,
        }
