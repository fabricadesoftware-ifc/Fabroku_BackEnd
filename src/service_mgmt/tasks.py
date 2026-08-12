"""Thin Celery tasks that wire real adapters to the service_mgmt use cases.

Each task's only job is: build the real Dokku adapter and call `.execute()`
(or the relevant `execute_*` method). All business logic lives in
`service_mgmt/use_cases/`.

`core/apps/views.py`/`serializers.py` dispatch these directly (Fase 4.5). The
legacy `CreateServiceMixin`/`CreateServiceStandaloneMixin`/`DeleteServiceMixin`/
`LinkServiceMixin`/`UnlinkServiceMixin` classes they replaced have been removed.
"""
from celery import shared_task

from infrastructure.adapters.dokku import DokkuAdapter
from service_mgmt.use_cases.create_service import (
    CreateServiceCommand,
    CreateServiceStandaloneCommand,
    CreateServiceUseCase,
)
from service_mgmt.use_cases.delete_service import DeleteServiceCommand, DeleteServiceUseCase
from service_mgmt.use_cases.link_service import LinkServiceCommand, LinkServiceUseCase
from service_mgmt.use_cases.unlink_service import UnlinkServiceCommand, UnlinkServiceUseCase


@shared_task(bind=True)
def create_service_task(self, app_id: int, service_type: str, service_id: int | None = None) -> dict:
    """Provision a Dokku service attached to an App via CreateServiceUseCase."""
    use_case = CreateServiceUseCase(dokku_port=DokkuAdapter())
    result = use_case.execute_attached(
        CreateServiceCommand(app_id=app_id, service_type=service_type, service_id=service_id, task_id=self.request.id)
    )
    return {'status': 'created', 'service_id': result.service_id, 'service_name': result.service_name}


@shared_task(bind=True)
def create_service_standalone_task(  # noqa: PLR0913, PLR0917
    self,
    project_id: int,
    service_type: str,
    name: str | None = None,
    service_id: int | None = None,
    password: str | None = None,
) -> dict:
    """Provision a Dokku service with no App attached via CreateServiceUseCase."""
    use_case = CreateServiceUseCase(dokku_port=DokkuAdapter())
    result = use_case.execute_standalone(
        CreateServiceStandaloneCommand(
            project_id=project_id,
            service_type=service_type,
            name=name,
            service_id=service_id,
            password=password,
            task_id=self.request.id,
        )
    )
    return {'status': 'created', 'service_id': result.service_id, 'service_name': result.service_name}


@shared_task(bind=True)
def delete_service_task(self, service_id: int, deleted_by_id: int | None = None) -> dict:
    """Unlink and delete a service via DeleteServiceUseCase."""
    use_case = DeleteServiceUseCase(dokku_port=DokkuAdapter())
    result = use_case.execute(
        DeleteServiceCommand(service_id=service_id, task_id=self.request.id, deleted_by_id=deleted_by_id)
    )
    return {'status': 'deleted', 'service_id': result.service_id}


@shared_task(bind=True)
def link_service_task(self, service_id: int, app_id: int) -> dict:
    """Link an existing service to an app via LinkServiceUseCase."""
    use_case = LinkServiceUseCase(dokku_port=DokkuAdapter())
    result = use_case.execute(LinkServiceCommand(service_id=service_id, app_id=app_id, task_id=self.request.id))
    return {'status': 'linked', 'service_id': result.service_id, 'app_id': result.app_id, 'env_key': result.env_key}


@shared_task(bind=True)
def unlink_service_task(self, service_id: int) -> dict:
    """Detach a service from its app via UnlinkServiceUseCase."""
    use_case = UnlinkServiceUseCase(dokku_port=DokkuAdapter())
    result = use_case.execute(UnlinkServiceCommand(service_id=service_id, task_id=self.request.id))
    return {'status': 'unlinked', 'service_id': result.service_id}
