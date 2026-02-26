import uuid
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import App, Service, ServiceType
from core.apps.utils import slugify_dokku
from core.logs.models import AppLogManager, LogCategory


def _check_dokku_output(output: str, operation: str):
    """Verifica se o output do Dokku indica erro e levanta exceção se necessário."""
    if not output:
        raise RuntimeError(f'{operation}: nenhuma resposta do servidor')
    output_lower = output.lower()
    if 'failed to execute command' in output_lower or 'ssh connection error' in output_lower:
        raise RuntimeError(f'{operation} falhou: {output}')


class CreateServiceMixin:
    """Mixin para criação de serviços (banco de dados, redis, etc.) via Celery."""

    @shared_task(bind=True)
    def create_service(
        self,
        app_id: int,
        service_type: str,
    ) -> dict:
        """
        Cria um serviço (ex: Postgres) no Dokku, vincula ao app,
        e a DATABASE_URL é automaticamente injetada pelo Dokku via link.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            app = App.objects.get(id=app_id)
        except App.DoesNotExist:
            return {'status': 'error', 'message': f'App {app_id} not found'}

        # Salva task_id no app
        app.task_id = task_id
        app.save(update_fields=['task_id'])

        logger = AppLogManager(app, task_id)
        dokku_adapter = DokkuAdapter()

        service_name = f'{app.name}-db'
        dokku_service_name = slugify_dokku(f'{service_name}-{app.project.id}')
        dokku_service_password = uuid.uuid4().hex

        if not app.name_dokku:
            logger.error('App não tem name_dokku configurado', category=LogCategory.DATABASE)
            return {'status': 'error', 'message': 'App sem name_dokku'}

        try:
            # === 1. Criar o serviço no Dokku ===
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
                        f'Banco {dokku_service_name} já existe, reutilizando...',
                        category=LogCategory.DATABASE,
                        progress=40,
                    )
                else:
                    _check_dokku_output(output, 'postgres:create')

            # === 2. Vincular ao app (injeta DATABASE_URL, mas usa --no-restart para evitar rebuild) ===
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
                    db_name=dokku_service_name, app_name=app.name_dokku, no_restart=True,
                )
                logger.dokku(
                    link_output,
                    command=f'postgres:link --no-restart {dokku_service_name} {app.name_dokku}',
                    category=LogCategory.DATABASE,
                    progress=70,
                )
                if 'already linked' in link_output.lower():
                    logger.info(
                        f'Banco já está vinculado ao app, continuando...',
                        category=LogCategory.DATABASE,
                        progress=70,
                    )
                else:
                    _check_dokku_output(link_output, 'postgres:link')

            # === 3. Garantir que o serviço está rodando após o link ===
            task.update_state(
                state='PROGRESS',
                meta={'current': 80, 'total': 100, 'status': 'Verificando serviço...'},
            )

            if service_type == ServiceType.POSTGRES:
                try:
                    dokku_adapter.start_database(dokku_service_name)
                except Exception:
                    pass

            # === 4. Salvar no banco de dados local ===
            task.update_state(
                state='PROGRESS',
                meta={'current': 90, 'total': 100, 'status': 'Salvando informações do serviço...'},
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

            logger.success(
                f'Banco de dados criado e vinculado com sucesso! DATABASE_URL foi injetada automaticamente.',
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
                f'Erro ao criar serviço: {str(e)}',
                category=LogCategory.DATABASE,
                metadata={'error_type': type(e).__name__, 'error_details': str(e)},
            )
            raise
