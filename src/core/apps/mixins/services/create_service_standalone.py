import logging
import time
import uuid
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import Project, Service, ServiceType
from core.apps.utils import slugify_dokku

logger = logging.getLogger(__name__)


def _check_dokku_output(output: str, operation: str):
    if not output:
        raise RuntimeError(f'{operation}: nenhuma resposta do servidor')
    output_lower = output.lower()
    if 'failed to execute command' in output_lower or 'ssh connection error' in output_lower:
        raise RuntimeError(f'{operation} falhou: {output}')


class CreateServiceStandaloneMixin:
    """Mixin para criação de serviços standalone (sem app)."""

    @shared_task(bind=True)
    def create_service_standalone(
        self,
        project_id: int,
        service_type: str,
        name: str | None = None,
        service_id: int | None = None,
        password: str | None = None,
    ) -> dict:
        """
        Cria um serviço no Dokku sem vincular a app.
        Apenas Postgres habilitado por enquanto.
        Se service_id for passado, atualiza o registro existente; senão cria novo.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return {'status': 'error', 'message': f'Projeto {project_id} não encontrado'}

        if service_type != ServiceType.POSTGRES:
            return {'status': 'error', 'message': 'Apenas Postgres está habilitado no momento'}

        dokku_service_name = slugify_dokku(name) if name else f'postgres-{uuid.uuid4().hex[:8]}'
        dokku_service_password = password or uuid.uuid4().hex
        service_name = name or dokku_service_name

        if service_id:
            service = Service.objects.get(id=service_id)
            service.task_id = task_id
            service.name = service_name
            service.password = dokku_service_password
            service.save(update_fields=['task_id', 'name', 'password'])
        else:
            service = Service.objects.create(
                name=service_name,
                service_type=service_type,
                user='postgres',
                password=dokku_service_password,
                host='provisionando...',
                port=5432,
                app=None,
                project=project,
                container_name=None,
                task_id=task_id,
            )

        dokku_adapter = DokkuAdapter()

        try:
            task.update_state(
                state='PROGRESS',
                meta={'current': 10, 'total': 100, 'status': f'Criando banco {dokku_service_name}...'},
            )
            logger.info('Criando banco PostgreSQL: %s', dokku_service_name)

            output = dokku_adapter.create_database(db_name=dokku_service_name, password=dokku_service_password)
            if 'already exists' in output.lower():
                logger.info('Banco %s já existe, reutilizando', dokku_service_name)
            else:
                _check_dokku_output(output, 'postgres:create')

            task.update_state(
                state='PROGRESS',
                meta={'current': 60, 'total': 100, 'status': 'Iniciando serviço...'},
            )

            start_output = dokku_adapter.start_database(dokku_service_name)
            if 'failed' in start_output.lower():
                if 'sethostname' in start_output.lower() or 'invalid argument' in start_output.lower():
                    dokku_adapter.remove_postgres_container(dokku_service_name)
                    time.sleep(2)
                    start_output = dokku_adapter.start_database(dokku_service_name)
                elif 'already in use' in start_output.lower() or 'conflict' in start_output.lower():
                    dokku_adapter.stop_database(dokku_service_name)
                    time.sleep(2)
                    start_output = dokku_adapter.start_database(dokku_service_name)
            time.sleep(2)

            service.container_name = dokku_service_name
            service.host = f'dokku-postgres-{dokku_service_name}'
            service.task_id = None
            service.save(update_fields=['container_name', 'host', 'task_id'])

            task.update_state(
                state='PROGRESS',
                meta={'current': 100, 'total': 100, 'status': 'Concluído!'},
            )
            logger.info('Banco %s criado com sucesso', dokku_service_name)

            return {
                'status': 'created',
                'service_id': service.id,
                'service_name': dokku_service_name,
                'service_type': service_type,
            }

        except Exception as e:
            logger.exception('Erro ao criar serviço: %s', e)
            service.delete()
            raise
