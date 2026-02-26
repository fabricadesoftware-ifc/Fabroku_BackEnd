from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App, Service, ServiceType
from core.logs.models import AppLogManager, LogCategory


class DeleteAppMixin:
    """Mixin para exclusão de aplicações via Celery."""

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
        logger.info(f'Iniciando remoção da aplicação {app.name}...', category=LogCategory.DEPLOY, progress=5)

        # === 1. Limpa serviços vinculados ===
        services = Service.objects.filter(app=app)
        total_services = services.count()

        for idx, service in enumerate(services):
            dokku_service_name = service.container_name or service.name
            progress = 10 + int((idx / max(total_services, 1)) * 40)

            task.update_state(
                state='PROGRESS',
                meta={'current': progress, 'total': 100, 'status': f'Removendo serviço {dokku_service_name}...'},
            )

            if service.service_type == ServiceType.POSTGRES and dokku_app_name:
                # Unlink
                try:
                    unlink_output = dokku_adapter.unlink_database(
                        db_name=dokku_service_name, app_name=dokku_app_name,
                    )
                    if 'failed' in unlink_output.lower():
                        logger.warning(
                            f'Unlink do banco {dokku_service_name} retornou erro: {unlink_output}',
                            category=LogCategory.DATABASE,
                            progress=progress,
                        )
                    else:
                        logger.info(
                            f'Banco {dokku_service_name} desvinculado do app',
                            category=LogCategory.DATABASE,
                            progress=progress,
                        )
                except Exception as e:
                    logger.warning(
                        f'Erro ao desvincular banco {dokku_service_name}: {e}',
                        category=LogCategory.DATABASE,
                        progress=progress,
                    )

                # Delete (remove container travado antes, se houver)
                try:
                    dokku_adapter.remove_postgres_container(dokku_service_name)
                    delete_output = dokku_adapter.delete_database(db_name=dokku_service_name)
                    if 'failed' in delete_output.lower():
                        logger.warning(
                            f'Deleção do banco {dokku_service_name} retornou erro: {delete_output}',
                            category=LogCategory.DATABASE,
                            progress=progress,
                        )
                    else:
                        logger.success(
                            f'Banco {dokku_service_name} removido do Dokku',
                            category=LogCategory.DATABASE,
                            progress=progress,
                        )
                except Exception as e:
                    logger.warning(
                        f'Erro ao deletar banco {dokku_service_name}: {e}',
                        category=LogCategory.DATABASE,
                        progress=progress,
                    )

            service.delete()

        # === 2. Deleta o app no Dokku ===
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
                if 'failed' in result.lower():
                    logger.warning(
                        f'Deleção do app retornou erro: {result}',
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

        # === 3. Remove do banco local ===
        app.delete()

        logger.success(
            f'Aplicação {app.name} removida com sucesso!',
            category=LogCategory.DEPLOY,
            progress=100,
        )

        return {'status': 'deleted', 'app_id': app_id, 'dokku_app': dokku_app_name}
