from typing import Literal, cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App
from core.logs.models import AppLogManager, LogCategory

ActionType = Literal['start', 'stop', 'restart']


class ManageAppMixin:
    """Mixin para gerenciamento de aplicações (start/stop/restart)."""

    @shared_task(bind=True)
    def manage_app_task(self, app_id: int, action: ActionType) -> dict:
        """
        Gerencia o estado de uma aplicação (start/stop/restart).
        """
        task = cast(Task, self)
        task_id = task.request.id

        action_messages = {
            'start': ('Iniciando', 'iniciada', 'RUNNING'),
            'stop': ('Parando', 'parada', 'STOPPED'),
            'restart': ('Reiniciando', 'reiniciada', 'RUNNING'),
        }

        try:
            app = App.objects.get(id=app_id, deleted_at__isnull=True)
        except App.DoesNotExist:
            return {'status': 'error', 'message': f'App {app_id} not found'}

        msg_progress, msg_done, final_status = action_messages[action]

        # Atualiza task_id
        app.task_id = task_id
        app.save(update_fields=['task_id'])

        # Inicializa logger
        logger = AppLogManager(app, task_id)
        logger.info(f'{msg_progress} aplicação...', category=LogCategory.DEPLOY, progress=10)

        dokku_adapter = DokkuAdapter()
        dokku_app_name = app.name_dokku

        if not dokku_app_name:
            logger.error('App não tem name_dokku configurado', category=LogCategory.DEPLOY)
            return {'status': 'error', 'message': 'App não tem name_dokku'}

        try:
            # Garante que serviços linkados estejam rodando antes de start/restart
            if action in ('start', 'restart'):
                from core.apps.models import Service  # noqa: PLC0415

                for svc in Service.objects.filter(app=app, deleted_at__isnull=True):
                    if svc.container_name and svc.service_type == 'postgres':
                        try:
                            dokku_adapter.start_database(svc.container_name)
                        except Exception:
                            pass

            task.update_state(
                state='PROGRESS',
                meta={'current': 30, 'total': 100, 'status': f'{msg_progress} aplicação...'},
            )

            # Executa a ação no Dokku
            if action == 'start':
                result = dokku_adapter.start_app(dokku_app_name)
            elif action == 'stop':
                result = dokku_adapter.stop_app(dokku_app_name)
            else:  # restart
                result = dokku_adapter.restart_app(dokku_app_name)

            logger.dokku(result, category=LogCategory.DEPLOY, progress=80)

            # Atualiza status
            app.status = final_status
            app.save(update_fields=['status'])

            logger.success(
                f'Aplicação {msg_done} com sucesso!',
                category=LogCategory.DEPLOY,
                progress=100,
            )

            return {
                'status': 'success',
                'action': action,
                'app_id': app_id,
                'dokku_app': dokku_app_name,
                'output': result,
            }

        except Exception as e:
            logger.error(f'Erro ao {action} aplicação: {str(e)}', category=LogCategory.DEPLOY)
            app.status = 'ERROR'
            app.save(update_fields=['status'])
            raise

    # Compatibilidade com chamadas legadas que usam AppMixin.manage_app.delay(...)
    manage_app = manage_app_task
