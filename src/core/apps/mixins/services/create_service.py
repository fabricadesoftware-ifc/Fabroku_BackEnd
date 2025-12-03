import uuid
from typing import cast

from celery import Task, shared_task

from core.adapters import DokkuAdapter
from core.apps.models import Service, ServiceType
from core.apps.utils import slugify_dokku

# postgres://{uuid}:{password}@proxy.pg.coolify.fabricadesoftware.ifc.edu.br:1022/{database}


class CreateServiceMixin:
    """Mixin para criação de serviços via Celery."""

    @shared_task(bind=True)
    def create_service(
        self,
        service_name: str,
        service_type: str,
        project_id: int,
        variables: dict | None = None,
    ) -> dict:
        task = cast(Task, self)

        dokku_adapter = DokkuAdapter()

        dokku_service_name = slugify_dokku(f"{service_name}-{project_id}")
        dokku_service_password = uuid.uuid4().hex

        task.update_state(state='PROGRESS', meta={'status': f'Criando serviço {dokku_service_name}...'})

        # Cria o serviço no Dokku
        if service_type == ServiceType.POSTGRES:
            dokku_adapter.create_database(db_name=dokku_service_name, password=dokku_service_password)

        # Cria o registro do serviço no banco de dados
        service = Service.objects.create(
            name=service_name,
            service_type=service_type,
            user=service_type,
            password=dokku_service_password,
            project_id=project_id,
        )

        return {'status': 'created', 'service_id': service.id, 'dokku_service_name': dokku_service_name}  # type: ignore
