"""DeleteServiceUseCase: business logic for deleting a service.

Ports `core/apps/mixins/services/delete_service.py` (`DeleteServiceMixin`)
faithfully: unlink from the app first (best-effort — the plugin's own unlink
failure doesn't abort), delete the remote service (also best-effort), soft-
delete the local record, then promote a remaining linked database to
DATABASE_URL if the deleted service held that env var.

Reuses `core.apps.mixins.services.service_dokku`'s `delete_dokku_service`/
`unlink_dokku_service`/`promote_remaining_database_if_needed` directly — same
as `DeleteAppUseCase`, they only depend on `IDokkuPort` methods.

Same deviation as every other Fase 4 use case: no `task.update_state(...)`
calls. "Service already deleted" (or already gone from the DB) stays an
idempotent success, same precedent as `DeleteAppUseCase`.
"""
from dataclasses import dataclass

from applications.ports.i_dokku import IDokkuPort
from core.apps.mixins.services.service_dokku import (
    check_dokku_output,
    delete_dokku_service,
    promote_remaining_database_if_needed,
    unlink_dokku_service,
)
from observability.models import AppLogManager, LogCategory
from service_mgmt.models import Service
from service_mgmt.service_types import ServiceRuntime, get_service_runtime


@dataclass(frozen=True)
class DeleteServiceCommand:
    service_id: int
    task_id: str | None = None
    deleted_by_id: int | None = None


@dataclass(frozen=True)
class ServiceDeleted:
    service_id: int
    already_deleted: bool = False


class DeleteServiceUseCase:
    """Unlink a service from its app, delete it in Dokku, and soft-delete the local record."""

    def __init__(self, dokku_port: IDokkuPort):
        self.dokku_port = dokku_port

    def execute(self, cmd: DeleteServiceCommand) -> ServiceDeleted:
        try:
            service = Service.objects.select_related('app', 'project').get(id=cmd.service_id)
        except Service.DoesNotExist:
            return ServiceDeleted(service_id=cmd.service_id, already_deleted=True)

        if service.deleted_at:
            return ServiceDeleted(service_id=service.id, already_deleted=True)

        runtime = get_service_runtime(service.service_type)
        app = service.app
        log_manager = self._prepare_task_context(service, cmd.task_id)

        removed_env_key = service.env_key or runtime.env_key
        self._unlink_remote_service_if_needed(service, runtime, log_manager)
        self._delete_remote_service(service, runtime, log_manager)

        service.soft_delete(deleted_by_id=cmd.deleted_by_id)

        if app:
            promote_remaining_database_if_needed(
                app=app,
                removed_env_key=removed_env_key,
                excluded_service_id=service.id,
                dokku_adapter=self.dokku_port,
                logger=log_manager,
                progress=90,
            )

        if log_manager:
            log_manager.success(
                f'Serviço {runtime.label} removido com sucesso!', category=LogCategory.DATABASE, progress=100
            )

        return ServiceDeleted(service_id=service.id)

    def _prepare_task_context(self, service: Service, task_id: str | None) -> AppLogManager | None:
        if not service.app:
            service.task_id = task_id
            service.save(update_fields=['task_id'])
            return None
        service.app.task_id = task_id
        service.app.save(update_fields=['task_id'])
        return AppLogManager(service.app, task_id)

    def _unlink_remote_service_if_needed(
        self, service: Service, runtime: ServiceRuntime, log_manager: AppLogManager | None
    ) -> None:
        app = service.app
        env_key = service.env_key or runtime.env_key
        dokku_service_name = service.container_name or service.name
        if not app:
            return

        if not app.name_dokku:
            self._remove_app_env_key(app, env_key)
            return

        if log_manager:
            log_manager.info(
                f'Desvinculando {runtime.label} {dokku_service_name} do app {app.name_dokku}...',
                category=LogCategory.DATABASE,
                progress=20,
            )

        unlink_succeeded = False
        if dokku_service_name:
            try:
                output, _command = unlink_dokku_service(self.dokku_port, runtime, dokku_service_name, app.name_dokku)
                if log_manager:
                    log_manager.dokku(output, category=LogCategory.DATABASE, progress=35)
                check_dokku_output(output, f'{runtime.default_prefix}:unlink', allow_empty=True)
                unlink_succeeded = True
            except Exception as exc:
                if log_manager:
                    log_manager.warning(
                        f'Unlink não confirmado; aplicando limpeza direta de {env_key}: {exc}',
                        category=LogCategory.DATABASE,
                        progress=35,
                    )

        should_unset = bool(env_key) and not unlink_succeeded
        if env_key and unlink_succeeded:
            current_value = self.dokku_port.get_config(app.name_dokku, env_key).strip()
            service_markers = tuple(
                marker
                for marker in (service.host, service.container_name, f'dokku-postgres-{service.container_name}')
                if marker
            )
            should_unset = bool(current_value) and any(marker in current_value for marker in service_markers)

        if env_key and should_unset:
            unset_output = self.dokku_port.unset_config(
                app_name=app.name_dokku, keys=[env_key], no_restart=unlink_succeeded
            )
            if log_manager:
                log_manager.dokku(unset_output, category=LogCategory.CONFIG, progress=45)
            check_dokku_output(unset_output, f'config:unset {env_key}', allow_empty=True)
        self._remove_app_env_key(app, env_key)

    def _remove_app_env_key(self, app, env_key: str | None) -> None:
        if env_key and app.variables and isinstance(app.variables, dict) and env_key in app.variables:
            app.variables = dict(app.variables)
            del app.variables[env_key]
            app.save(update_fields=['variables'])

    def _delete_remote_service(
        self, service: Service, runtime: ServiceRuntime, log_manager: AppLogManager | None
    ) -> None:
        dokku_service_name = service.container_name or service.name
        if log_manager:
            log_manager.info(
                f'Deletando {runtime.label} {dokku_service_name} do Dokku...',
                category=LogCategory.DATABASE,
                progress=50,
            )
        try:
            output, _command = delete_dokku_service(self.dokku_port, runtime, dokku_service_name)
            if log_manager:
                log_manager.dokku(output, category=LogCategory.DATABASE, progress=80)
        except Exception as e:
            if log_manager:
                log_manager.warning(
                    f'Erro ao deletar no Dokku (continuando...): {e}', category=LogCategory.DATABASE, progress=80
                )
