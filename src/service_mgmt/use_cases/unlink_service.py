"""UnlinkServiceUseCase: business logic for detaching a service from its App
without deleting it.

Ports `core/apps/mixins/services/unlink_service.py` (`UnlinkServiceMixin`)
faithfully: unlink in Dokku, remove the mirrored env var from the app,
detach the local record, and promote a remaining linked database to
DATABASE_URL if the detached service held that env var.

Same deviation as every other Fase 4 use case: no `task.update_state(...)`
calls. "Service not linked to any app" becomes `ApplicationDomainError`
instead of a silent `return {'status': 'error', ...}`, same shape as
`LinkServiceUseCase`'s validation errors.
"""
from dataclasses import dataclass

from applications.domain.exceptions import ApplicationDomainError
from applications.ports.i_dokku import IDokkuPort
from core.apps.mixins.services.service_dokku import (
    check_dokku_output,
    promote_remaining_database_if_needed,
    unlink_dokku_service,
)
from observability.models import AppLogManager, LogCategory
from service_mgmt.models import Service
from service_mgmt.service_types import get_service_runtime


@dataclass(frozen=True)
class UnlinkServiceCommand:
    service_id: int
    task_id: str | None = None


@dataclass(frozen=True)
class ServiceUnlinked:
    service_id: int


class UnlinkServiceUseCase:
    """Detach a service from its app without deleting it."""

    def __init__(self, dokku_port: IDokkuPort):
        self.dokku_port = dokku_port

    def execute(self, cmd: UnlinkServiceCommand) -> ServiceUnlinked:
        service = Service.objects.select_related('app', 'project').get(id=cmd.service_id, deleted_at__isnull=True)

        app = service.app
        if not app:
            raise ApplicationDomainError('Serviço não está vinculado a nenhum app')

        runtime = get_service_runtime(service.service_type)

        app.task_id = cmd.task_id
        app.save(update_fields=['task_id'])

        log_manager = AppLogManager(app, cmd.task_id)
        dokku_service_name = service.container_name

        if not dokku_service_name or not app.name_dokku:
            service.app = None
            service.save(update_fields=['app'])
            return ServiceUnlinked(service_id=service.id)

        removed_env_key = service.env_key or runtime.env_key
        log_manager.info('Desvinculando serviço...', category=LogCategory.DATABASE, progress=30)

        unlink_output, _command = unlink_dokku_service(self.dokku_port, runtime, dokku_service_name, app.name_dokku)
        log_manager.dokku(unlink_output, category=LogCategory.DATABASE, progress=60)
        check_dokku_output(unlink_output, f'{runtime.default_prefix}:unlink', allow_empty=True)

        if app.variables and isinstance(app.variables, dict) and removed_env_key in app.variables:
            app.variables = dict(app.variables)
            del app.variables[removed_env_key]
            app.save(update_fields=['variables'])
            log_manager.info(
                f'{removed_env_key} removida das variáveis do app', category=LogCategory.CONFIG, progress=80
            )

        service.app = None
        service.env_key = None
        service.save(update_fields=['app', 'env_key'])

        promote_remaining_database_if_needed(
            app=app,
            removed_env_key=removed_env_key,
            excluded_service_id=service.id,
            dokku_adapter=self.dokku_port,
            logger=log_manager,
            progress=90,
        )

        log_manager.success(
            f'Serviço {runtime.label} desvinculado com sucesso!', category=LogCategory.DATABASE, progress=100
        )

        return ServiceUnlinked(service_id=service.id)
