from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App, Service, ServiceType
from core.logs.models import AppLogManager, LogCategory


class DeleteServiceMixin:
    """Mixin para exclusão de serviços (banco de dados, redis, etc.) via Celery."""

    @shared_task(bind=True)
    def delete_service(self, service_id: int) -> dict:
        """
        Desvincula o serviço do app no Dokku, deleta o serviço,
        e remove o registro do banco local.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            service = Service.objects.select_related('app', 'project').get(id=service_id)
        except Service.DoesNotExist:
            return {'status': 'deleted', 'message': 'Service already deleted'}

        app = service.app
        dokku_adapter = DokkuAdapter()

        # Salva task_id no app
        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_service_name = service.container_name or service.name

        try:
            # === 1. Desvincular do app ===
            if app.name_dokku and dokku_service_name:
                task.update_state(
                    state='PROGRESS',
                    meta={'current': 20, 'total': 100, 'status': 'Desvinculando banco do app...'},
                )
                logger.info(
                    f'Desvinculando banco {dokku_service_name} do app {app.name_dokku}...',
                    category=LogCategory.DATABASE,
                    progress=20,
                )

                try:
                    if service.service_type == ServiceType.POSTGRES:
                        output = dokku_adapter.unlink_database(
                            db_name=dokku_service_name,
                            app_name=app.name_dokku,
                        )
                        logger.dokku(
                            output,
                            command=f'postgres:unlink {dokku_service_name} {app.name_dokku}',
                            category=LogCategory.DATABASE,
                            progress=40,
                        )
                except Exception as e:
                    logger.warning(
                        f'Erro ao desvincular (pode já estar desvinculado): {str(e)}',
                        category=LogCategory.DATABASE,
                        progress=40,
                    )

            # === 2. Deletar o serviço no Dokku ===
            task.update_state(
                state='PROGRESS',
                meta={'current': 50, 'total': 100, 'status': f'Deletando banco {dokku_service_name}...'},
            )
            logger.info(
                f'Deletando banco {dokku_service_name} do Dokku...',
                category=LogCategory.DATABASE,
                progress=50,
            )

            try:
                if service.service_type == ServiceType.POSTGRES:
                    dokku_adapter.remove_postgres_container(dokku_service_name)
                    output = dokku_adapter.delete_database(db_name=dokku_service_name)
                    logger.dokku(
                        output,
                        command=f'postgres:destroy {dokku_service_name} --force',
                        category=LogCategory.DATABASE,
                        progress=80,
                    )
            except Exception as e:
                logger.warning(
                    f'Erro ao deletar no Dokku (continuando...): {str(e)}',
                    category=LogCategory.DATABASE,
                    progress=80,
                )

            # === 3. Remover registro local ===
            service_id_saved = service.id
            service.delete()

            logger.success(
                'Banco de dados removido com sucesso! DATABASE_URL foi desvinculada do app.',
                category=LogCategory.DATABASE,
                progress=100,
            )

            return {
                'status': 'deleted',
                'service_id': service_id_saved,
            }

        except Exception as e:
            logger.error(
                f'Erro ao deletar serviço: {str(e)}',
                category=LogCategory.DATABASE,
                metadata={'error_type': type(e).__name__, 'error_details': str(e)},
            )
            raise
