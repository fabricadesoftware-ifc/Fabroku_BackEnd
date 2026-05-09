import logging
import time
import uuid
from dataclasses import dataclass
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.mixins.services.service_dokku import (
    check_dokku_output,
    create_dokku_service,
    start_dokku_service,
)
from core.apps.models import Project, Service, ServiceType
from core.apps.service_types import ServiceRuntime, get_service_runtime
from core.apps.utils import slugify_dokku

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceRecordInput:
    project: Project
    runtime: ServiceRuntime
    service_name: str
    password: str
    task_id: str
    service_id: int | None


def _service_password(runtime: ServiceRuntime, password: str | None) -> str:
    if password is not None:
        return password
    return uuid.uuid4().hex if runtime.service_type == ServiceType.POSTGRES.value else ''


def _prepare_service_record(payload: ServiceRecordInput) -> Service:
    if not payload.service_id:
        return Service.objects.create(
            name=payload.service_name,
            service_type=payload.runtime.service_type,
            user=payload.runtime.user,
            password=payload.password,
            host='provisionando...',
            port=payload.runtime.port,
            app=None,
            project=payload.project,
            container_name=None,
            task_id=payload.task_id,
        )

    service = Service.objects.get(id=payload.service_id)
    service.task_id = payload.task_id
    service.name = payload.service_name
    service.service_type = payload.runtime.service_type
    service.user = payload.runtime.user
    service.password = payload.password
    service.port = payload.runtime.port
    service.save(update_fields=['task_id', 'name', 'service_type', 'user', 'password', 'port'])
    return service


class CreateServiceStandaloneMixin:
    """Mixin para criacao de servicos standalone (sem app)."""

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
        Cria um servico no Dokku sem vincular a app.

        Se service_id for passado, atualiza o registro placeholder criado pela API;
        senao cria o registro local depois do provisionamento.
        """
        task = cast(Task, self)
        task_id = task.request.id

        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return {'status': 'error', 'message': f'Projeto {project_id} nao encontrado'}

        try:
            runtime = get_service_runtime(service_type)
        except ValueError as exc:
            return {'status': 'error', 'message': str(exc)}

        dokku_service_name = slugify_dokku(name) if name else f'{runtime.default_prefix}-{uuid.uuid4().hex[:8]}'
        service_password = _service_password(runtime, password)
        service = _prepare_service_record(
            ServiceRecordInput(
                project=project,
                runtime=runtime,
                service_name=name or dokku_service_name,
                password=service_password,
                task_id=task_id,
                service_id=service_id,
            )
        )
        dokku_adapter = DokkuAdapter()

        try:
            task.update_state(
                state='PROGRESS',
                meta={
                    'current': 10,
                    'total': 100,
                    'status': f'Criando servico {runtime.label} {dokku_service_name}...',
                },
            )
            logger.info('Criando servico %s: %s', runtime.label, dokku_service_name)

            output, _command, operation = create_dokku_service(
                dokku_adapter,
                runtime,
                dokku_service_name,
                service_password,
            )
            if 'already exists' in output.lower():
                logger.info('Servico %s ja existe, reutilizando', dokku_service_name)
            else:
                check_dokku_output(output, operation)

            task.update_state(
                state='PROGRESS',
                meta={'current': 60, 'total': 100, 'status': 'Iniciando servico...'},
            )
            start_output = start_dokku_service(dokku_adapter, runtime, dokku_service_name)
            check_dokku_output(start_output, f'{runtime.default_prefix}:start')
            if runtime.service_type == ServiceType.POSTGRES.value:
                time.sleep(2)

            service.container_name = dokku_service_name
            service.host = f'{runtime.host_prefix}{dokku_service_name}'
            service.port = runtime.port
            service.task_id = None
            service.save(update_fields=['container_name', 'host', 'port', 'task_id'])

            task.update_state(
                state='PROGRESS',
                meta={'current': 100, 'total': 100, 'status': 'Concluido!'},
            )
            logger.info('Servico %s criado com sucesso', dokku_service_name)

            return {
                'status': 'created',
                'service_id': service.id,
                'service_name': dokku_service_name,
                'service_type': runtime.service_type,
            }

        except Exception as e:
            logger.exception('Erro ao criar servico: %s', e)
            service.delete()
            raise
