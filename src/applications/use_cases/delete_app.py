"""DeleteAppUseCase: business logic for deleting an application and its linked services.

Ports `core/apps/mixins/apps/delete_app.py` (`DeleteAppMixin.delete_app`)
faithfully: unlink and delete every linked service (best-effort — failures are
logged, never abort the deletion), delete the app container, soft-delete
everything in the DB. Reuses `core.apps.mixins.services.service_dokku`'s
`delete_dokku_service`/`unlink_dokku_service` helpers as-is — they already
only call methods that live on `IDokkuPort`, so no reimplementation needed.

Same deviation as the other Fase 2/4 use cases: no `task.update_state(...)`
calls. Unlike Create/Deploy/Update/Manage, "app already deleted" (or already
gone from the DB) is a legitimate idempotent success here, not a failure
being hidden — so, faithful to the legacy mixin, it stays a normal return
value instead of becoming a raised exception.
"""
from dataclasses import dataclass

from applications.models import App
from applications.ports.i_dokku import IDokkuPort
from core.apps.mixins.services.service_dokku import delete_dokku_service, dokku_output_failed, unlink_dokku_service
from observability.models import AppLogManager, LogCategory
from service_mgmt.models import Service
from service_mgmt.service_types import get_service_runtime


@dataclass(frozen=True)
class DeleteAppCommand:
    app_id: int
    task_id: str | None = None
    deleted_by_id: int | None = None


@dataclass(frozen=True)
class AppDeleted:
    app_id: int
    dokku_app_name: str | None
    already_deleted: bool = False


class DeleteAppUseCase:
    """Delete an App: unlink/delete its services, delete the Dokku container, soft-delete both."""

    def __init__(self, dokku_port: IDokkuPort, log_manager: AppLogManager):
        self.dokku_port = dokku_port
        self.log_manager = log_manager

    def execute(self, cmd: DeleteAppCommand) -> AppDeleted:
        try:
            app = App.objects.get(id=cmd.app_id)
        except App.DoesNotExist:
            return AppDeleted(app_id=cmd.app_id, dokku_app_name=None, already_deleted=True)

        if app.deleted_at:
            return AppDeleted(app_id=app.id, dokku_app_name=app.name_dokku, already_deleted=True)

        app.task_id = cmd.task_id
        app.save(update_fields=['task_id'])

        dokku_app_name = app.name_dokku

        self.log_manager.info(
            f'Iniciando remoção da aplicação {app.name}...', category=LogCategory.DEPLOY, progress=5
        )

        services = Service.objects.filter(app=app, deleted_at__isnull=True)
        total_services = services.count()
        for idx, service in enumerate(services):
            progress = 10 + int((idx / max(total_services, 1)) * 40)
            self._delete_linked_service(service, dokku_app_name, cmd.deleted_by_id, progress)

        if dokku_app_name:
            self.log_manager.info(
                f'Removendo app {dokku_app_name} do Dokku...', category=LogCategory.DEPLOY, progress=60
            )
            try:
                result = self.dokku_port.delete_app(dokku_app_name)
                if dokku_output_failed(result):
                    self.log_manager.warning(
                        f'Deleção do app retornou erro: {result}', category=LogCategory.DEPLOY, progress=80
                    )
                else:
                    self.log_manager.dokku(result, category=LogCategory.DEPLOY, progress=80)
            except Exception as e:
                self.log_manager.warning(
                    f'Erro ao deletar app no Dokku: {e}', category=LogCategory.DEPLOY, progress=80
                )

        self.log_manager.success(
            f'Aplicação {app.name} removida com sucesso!', category=LogCategory.DEPLOY, progress=100
        )
        app.soft_delete(deleted_by_id=cmd.deleted_by_id)

        return AppDeleted(app_id=app.id, dokku_app_name=dokku_app_name)

    def _delete_linked_service(
        self, service: Service, dokku_app_name: str | None, deleted_by_id: int | None, progress: int
    ) -> None:
        dokku_service_name = service.container_name or service.name

        try:
            runtime = get_service_runtime(service.service_type)
        except ValueError:
            service.soft_delete(deleted_by_id=deleted_by_id)
            return

        if dokku_app_name:
            try:
                unlink_output, _command = unlink_dokku_service(
                    self.dokku_port, runtime, dokku_service_name, dokku_app_name
                )
                if dokku_output_failed(unlink_output):
                    self.log_manager.warning(
                        f'Unlink do serviço {dokku_service_name} retornou erro: {unlink_output}',
                        category=LogCategory.DATABASE,
                        progress=progress,
                    )
                else:
                    self.log_manager.info(
                        f'Serviço {dokku_service_name} desvinculado do app',
                        category=LogCategory.DATABASE,
                        progress=progress,
                    )
            except Exception as e:
                self.log_manager.warning(
                    f'Erro ao desvincular serviço {dokku_service_name}: {e}',
                    category=LogCategory.DATABASE,
                    progress=progress,
                )

        try:
            delete_output, _command = delete_dokku_service(self.dokku_port, runtime, dokku_service_name)
            if dokku_output_failed(delete_output):
                self.log_manager.warning(
                    f'Deleção do serviço {dokku_service_name} retornou erro: {delete_output}',
                    category=LogCategory.DATABASE,
                    progress=progress,
                )
            else:
                self.log_manager.success(
                    f'Serviço {dokku_service_name} removido do Dokku',
                    category=LogCategory.DATABASE,
                    progress=progress,
                )
        except Exception as e:
            self.log_manager.warning(
                f'Erro ao deletar serviço {dokku_service_name}: {e}',
                category=LogCategory.DATABASE,
                progress=progress,
            )

        service.soft_delete(deleted_by_id=deleted_by_id)
