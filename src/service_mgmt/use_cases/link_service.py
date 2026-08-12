"""LinkServiceUseCase: business logic for linking an existing (unattached or
detached) service to an App.

Ports `core/apps/mixins/services/link_service.py` (`LinkServiceMixin`)
faithfully: validate service/app compatibility, allocate a stable env key,
link in Dokku, sync the connection URL, restart the app once.

Same deviation as every other Fase 4 use case: no `task.update_state(...)`
calls. `Service`/`App` `DoesNotExist` are left to propagate naturally, same
precedent as `UpdateAppUseCase`. The legacy mixin's compatibility checks
(different project, already linked elsewhere, missing `name_dokku`/
`container_name`) become a plain `ApplicationDomainError` instead of a
silent `return {'status': 'error', ...}` — there isn't a recurring enough
shape here to warrant one dedicated exception class per check, unlike
`RunCommandUseCase`'s `CommandNotAllowed`.
"""
from dataclasses import dataclass

from django.db import transaction

from applications.domain.exceptions import ApplicationDomainError
from applications.models import App
from applications.ports.i_dokku import IDokkuPort
from core.apps.mixins.services.service_dokku import check_dokku_output, link_dokku_service, sync_service_url_from_dokku
from core.apps.mixins.services.service_env import allocate_service_env_key
from observability.models import AppLogManager, LogCategory
from service_mgmt.models import Service
from service_mgmt.service_types import get_service_runtime


@dataclass(frozen=True)
class LinkServiceCommand:
    service_id: int
    app_id: int
    task_id: str | None = None


@dataclass(frozen=True)
class ServiceLinked:
    service_id: int
    app_id: int
    env_key: str


class LinkServiceUseCase:
    """Link an existing service to an app and sync its connection URL."""

    def __init__(self, dokku_port: IDokkuPort):
        self.dokku_port = dokku_port

    def execute(self, cmd: LinkServiceCommand) -> ServiceLinked:
        service = Service.objects.select_related('project').get(id=cmd.service_id, deleted_at__isnull=True)
        app = App.objects.select_related('project').get(id=cmd.app_id, deleted_at__isnull=True)

        if service.project_id != app.project_id:
            raise ApplicationDomainError('Serviço e app devem pertencer ao mesmo projeto')
        if service.app_id and service.app_id != app.id:
            raise ApplicationDomainError(f'Serviço já vinculado ao app {service.app_id}')
        if not app.name_dokku:
            raise ApplicationDomainError('App sem name_dokku configurado')
        if not service.container_name:
            raise ApplicationDomainError('Serviço sem container_name')

        runtime = get_service_runtime(service.service_type)

        if not service.env_key:
            with transaction.atomic():
                locked_app = App.objects.select_for_update().get(id=app.id)
                service.env_key = allocate_service_env_key(
                    app=locked_app, service_name=service.name, runtime=runtime, exclude_service_id=service.id
                )
                service.save(update_fields=['env_key'])

        app.task_id = cmd.task_id
        app.save(update_fields=['task_id'])

        log_manager = AppLogManager(app, cmd.task_id)
        dokku_service_name = service.container_name

        log_manager.info(
            f'Vinculando {runtime.label} {dokku_service_name} ao app {app.name_dokku}...',
            category=LogCategory.DATABASE,
            progress=20,
        )

        link_output, _command, link_operation = link_dokku_service(
            self.dokku_port, runtime, dokku_service_name, app.name_dokku, no_restart=True, env_key=service.env_key
        )
        log_manager.dokku(link_output, category=LogCategory.DATABASE, progress=50)
        if 'already linked' not in link_output.lower():
            check_dokku_output(link_output, link_operation)

        sync_service_url_from_dokku(
            app=app,
            dokku_adapter=self.dokku_port,
            logger=log_manager,
            runtime=runtime,
            env_key=service.env_key,
            progress=80,
        )

        service.app = app
        service.task_id = None
        service.save(update_fields=['app', 'env_key', 'task_id'])

        restart_output = self.dokku_port.restart_app(app.name_dokku)
        log_manager.dokku(restart_output, category=LogCategory.DEPLOY, progress=90)

        log_manager.success(
            f'Serviço {runtime.label} vinculado ao app {app.name} com sucesso!',
            category=LogCategory.DATABASE,
            progress=100,
        )

        return ServiceLinked(service_id=service.id, app_id=app.id, env_key=service.env_key)
