import time
import uuid
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.mixins.services.database_url import sync_database_url_from_dokku
from core.apps.models import App, Service, ServiceType
from core.apps.utils import slugify_dokku
from core.logs.models import AppLogManager, LogCategory


def _check_dokku_output(output: str, operation: str):
    """Raise when Dokku returned an operational error."""
    if not output:
        raise RuntimeError(f'{operation}: nenhuma resposta do servidor')

    output_lower = output.lower()
    if 'failed to execute command' in output_lower or 'ssh connection error' in output_lower:
        raise RuntimeError(f'{operation} falhou: {output}')


class CreateServiceMixin:
    """Mixin para criacao de servicos via Celery."""

    @shared_task(bind=True)
    def create_service(
        self,
        app_id: int,
        service_type: str,
    ) -> dict:
        """
        Cria um servico no Dokku, vincula ao app e espelha a DATABASE_URL.

        O link com --no-restart evita restart automatico no meio do fluxo. Depois
        que a DATABASE_URL foi sincronizada no banco local, reiniciamos o app uma
        unica vez para que o runtime enxergue a nova variavel.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id)
        except App.DoesNotExist:
            return {'status': 'error', 'message': f'App {app_id} not found'}

        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()

        service_name = f'{app.name}-db'
        dokku_service_name = slugify_dokku(f'{service_name}-{app.id}')
        dokku_service_password = uuid.uuid4().hex

        if not app.name_dokku:
            logger.error('App sem name_dokku configurado', category=LogCategory.DATABASE)
            return {'status': 'error', 'message': 'App sem name_dokku'}

        try:
            task.update_state(
                state='PROGRESS',
                meta={'current': 10, 'total': 100, 'status': f'Criando banco {dokku_service_name}...'},
            )
            logger.info(
                f'Criando banco de dados PostgreSQL: {dokku_service_name}...',
                category=LogCategory.DATABASE,
                progress=10,
            )

            if service_type == ServiceType.POSTGRES:
                output = dokku_adapter.create_database(db_name=dokku_service_name, password=dokku_service_password)
                logger.dokku(
                    output,
                    command=f'postgres:create {dokku_service_name}',
                    category=LogCategory.DATABASE,
                    progress=40,
                )
                if 'already exists' in output.lower():
                    logger.info(
                        f'Banco {dokku_service_name} ja existe, reutilizando...',
                        category=LogCategory.DATABASE,
                        progress=40,
                    )
                else:
                    _check_dokku_output(output, 'postgres:create')

            task.update_state(
                state='PROGRESS',
                meta={'current': 50, 'total': 100, 'status': 'Vinculando banco ao app...'},
            )
            logger.info(
                f'Vinculando banco {dokku_service_name} ao app {app.name_dokku}...',
                category=LogCategory.DATABASE,
                progress=50,
            )

            if service_type == ServiceType.POSTGRES:
                link_output = dokku_adapter.link_database(
                    db_name=dokku_service_name,
                    app_name=app.name_dokku,
                    no_restart=True,
                )
                logger.dokku(
                    link_output,
                    command=f'postgres:link --no-restart {dokku_service_name} {app.name_dokku}',
                    category=LogCategory.DATABASE,
                    progress=70,
                )
                if 'already linked' in link_output.lower():
                    logger.info(
                        'Banco ja estava vinculado ao app, continuando...',
                        category=LogCategory.DATABASE,
                        progress=70,
                    )
                else:
                    _check_dokku_output(link_output, 'postgres:link')

                sync_database_url_from_dokku(
                    app=app,
                    dokku_adapter=dokku_adapter,
                    logger=logger,
                    progress=72,
                )

            task.update_state(
                state='PROGRESS',
                meta={'current': 80, 'total': 100, 'status': 'Iniciando servico...'},
            )

            if service_type == ServiceType.POSTGRES:
                start_output = dokku_adapter.start_database(dokku_service_name)
                if 'failed' in start_output.lower():
                    if 'sethostname' in start_output.lower() or 'invalid argument' in start_output.lower():
                        logger.info(
                            'Container travado por hostname invalido, removendo...',
                            category=LogCategory.DATABASE,
                            progress=82,
                        )
                        dokku_adapter.remove_postgres_container(dokku_service_name)
                        time.sleep(2)
                        start_output = dokku_adapter.start_database(dokku_service_name)
                    elif 'already in use' in start_output.lower() or 'conflict' in start_output.lower():
                        logger.info(
                            'Container em conflito, tentando postgres:stop antes de start...',
                            category=LogCategory.DATABASE,
                            progress=82,
                        )
                        dokku_adapter.stop_database(dokku_service_name)
                        time.sleep(2)
                        start_output = dokku_adapter.start_database(dokku_service_name)

                    if 'failed' in start_output.lower():
                        logger.warning(
                            f'postgres:start retornou: {start_output}',
                            category=LogCategory.DATABASE,
                            progress=82,
                        )
                    else:
                        logger.info(
                            f'Servico Postgres {dokku_service_name} iniciado',
                            category=LogCategory.DATABASE,
                            progress=82,
                        )
                else:
                    logger.info(
                        f'Servico Postgres {dokku_service_name} iniciado',
                        category=LogCategory.DATABASE,
                        progress=82,
                    )
                time.sleep(3)

            task.update_state(
                state='PROGRESS',
                meta={'current': 90, 'total': 100, 'status': 'Salvando informacoes do servico...'},
            )

            service = Service.objects.create(
                name=service_name,
                service_type=service_type,
                user='postgres' if service_type == ServiceType.POSTGRES else service_type,
                password=dokku_service_password,
                host=f'dokku-postgres-{dokku_service_name}',
                port=5432 if service_type == ServiceType.POSTGRES else 0,
                app=app,
                project=app.project,
                container_name=dokku_service_name,
            )

            if service_type == ServiceType.POSTGRES:
                task.update_state(
                    state='PROGRESS',
                    meta={'current': 94, 'total': 100, 'status': 'Reiniciando app para aplicar DATABASE_URL...'},
                )
                restart_output = dokku_adapter.restart_app(app.name_dokku)
                logger.dokku(
                    restart_output,
                    command=f'ps:restart {app.name_dokku}',
                    category=LogCategory.DEPLOY,
                    progress=94,
                )

            logger.success(
                'Banco de dados criado e vinculado com sucesso. DATABASE_URL sincronizada.',
                category=LogCategory.DATABASE,
                progress=100,
            )

            return {
                'status': 'created',
                'service_id': service.id,  # type: ignore
                'service_name': dokku_service_name,
                'service_type': service_type,
            }

        except Exception as e:
            logger.error(
                f'Erro ao criar servico: {str(e)}',
                category=LogCategory.DATABASE,
                metadata={'error_type': type(e).__name__, 'error_details': str(e)},
            )
            raise
