"""DeleteAppUseCase: business logic for deleting an application and its linked services.

Ports `core/apps/mixins/apps/delete_app.py` (`DeleteAppMixin.delete_app`)
faithfully: unlink and delete every linked service (best-effort — failures are
logged, never abort the deletion), delete the app container, soft-delete
everything in the DB. Reuses `core.apps.mixins.services.service_dokku`'s
`delete_dokku_service`/`unlink_dokku_service` helpers as-is — they already
only call methods that live on `IDokkuPort`, so no reimplementation needed.

Deviation from the legacy mixin: if the Dokku container cannot be removed,
the App is NOT soft-deleted (status=ERROR + InfrastructureError) — soft-deleting
it anyway left orphan containers running on Dokku with no DB record.

Same deviation as the other Fase 2/4 use cases: no `task.update_state(...)`
calls. Unlike Create/Deploy/Update/Manage, "app already deleted" (or already
gone from the DB) is a legitimate idempotent success here, not a failure
being hidden — so, faithful to the legacy mixin, it stays a normal return
value instead of becoming a raised exception.
"""
from dataclasses import dataclass

from applications.domain.exceptions import InfrastructureError
from applications.github_integration import remove_github_webhook
from applications.models import App, AppStatus
from applications.ownership import claim_app, save_if_owner
from applications.ports.i_dokku import IDokkuPort
from applications.ports.i_github import IGitHubPort
from core.apps.mixins.services.service_dokku import delete_dokku_service, dokku_output_failed, unlink_dokku_service
from identity.models import User
from observability.admin_notifications import notify_admins
from observability.models import AdminNotificationEvent, AppLogManager, LogCategory
from service_mgmt.models import Service
from service_mgmt.service_types import get_service_runtime


def _notify_service_delete_failed(service: Service, dokku_service_name: str, detail: str) -> None:
    notify_admins(
        AdminNotificationEvent.SERVICE_DELETE_FAILED,
        f'Falha ao apagar o serviço {dokku_service_name} no Dokku',
        detail,
        app=service.app,
        service=service,
        metadata={'dokku_service': dokku_service_name},
    )


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


VOLUME_IN_USE_MARKER = 'volume is in use'


class DeleteAppUseCase:
    """Delete an App: unlink/delete its services, delete the Dokku container, soft-delete both."""

    def __init__(self, dokku_port: IDokkuPort, log_manager: AppLogManager, github_port: IGitHubPort | None = None):
        self.dokku_port = dokku_port
        self.log_manager = log_manager
        self.github_port = github_port

    def execute(self, cmd: DeleteAppCommand) -> AppDeleted:
        try:
            app = App.objects.get(id=cmd.app_id)
        except App.DoesNotExist:
            return AppDeleted(app_id=cmd.app_id, dokku_app_name=None, already_deleted=True)

        if app.deleted_at:
            return AppDeleted(app_id=app.id, dokku_app_name=app.name_dokku, already_deleted=True)

        claim_app(app, cmd.task_id)

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
            failure = self._delete_dokku_app(dokku_app_name)
            if failure:
                save_if_owner(
                    app, cmd.task_id, status=AppStatus.ERROR, error_type='DeleteAppFailed', error_details=failure
                )
                self.log_manager.error(
                    f'Não foi possível remover {dokku_app_name} do Dokku; a aplicação não foi apagada. '
                    'Tente apagar novamente.',
                    category=LogCategory.DEPLOY,
                    progress=100,
                    metadata={'output': failure[:2000]},
                )
                notify_admins(
                    AdminNotificationEvent.APP_DELETE_FAILED,
                    f'Falha ao apagar o app {dokku_app_name} no Dokku',
                    failure,
                    app=app,
                    metadata={'dokku_app': dokku_app_name, 'deleted_by_id': cmd.deleted_by_id},
                )
                raise InfrastructureError('Falha ao remover app do Dokku', details=failure)

        self._remove_github_webhook(app, cmd.deleted_by_id)

        self.log_manager.success(
            f'Aplicação {app.name} removida com sucesso!', category=LogCategory.DEPLOY, progress=100
        )
        app.soft_delete(deleted_by_id=cmd.deleted_by_id)

        return AppDeleted(app_id=app.id, dokku_app_name=dokku_app_name)

    def _destroy(self, dokku_app_name: str) -> tuple[str | None, str | None]:
        """Roda `apps:destroy`; devolve (saida, falha)."""
        try:
            result = self.dokku_port.delete_app(dokku_app_name)
        except Exception as e:
            return None, str(e) or e.__class__.__name__
        return result, (result if dokku_output_failed(result) else None)

    def _delete_dokku_app(self, dokku_app_name: str) -> str | None:
        """Remove o container; retorna a mensagem de falha, ou None se o app nao existe mais no Dokku."""
        result, failure = self._destroy(dokku_app_name)

        if failure and VOLUME_IN_USE_MARKER in failure:
            # Container parado de build/release interrompido segura o volume de cache.
            self.log_manager.warning(
                'Um container parado do app está prendendo o volume de cache; limpando e tentando de novo...',
                category=LogCategory.DEPLOY,
                progress=70,
            )
            try:
                self.dokku_port.cleanup_app(dokku_app_name)
            except Exception as e:
                self.log_manager.warning(f'Falha ao limpar containers parados: {e}', category=LogCategory.DEPLOY)
            result, failure = self._destroy(dokku_app_name)

        if not failure:
            self.log_manager.dokku(result, category=LogCategory.DEPLOY, progress=80)
            return None

        # Falha na resposta mas o app ja sumiu (ex: timeout depois do destroy): segue com o soft delete.
        try:
            if not self.dokku_port.exists_app(dokku_app_name):
                self.log_manager.warning(
                    f'Deleção do app retornou erro, mas {dokku_app_name} já não existe no Dokku: {failure}',
                    category=LogCategory.DEPLOY,
                    progress=80,
                )
                return None
        except Exception:
            pass
        return failure

    def _remove_github_webhook(self, app: App, deleted_by_id: int | None) -> None:
        """Best-effort: sem isso, o GitHub continua mandando push events pro app apagado."""
        if not self.github_port or not app.git:
            return

        preferred_user = User.objects.filter(id=deleted_by_id).first() if deleted_by_id else None

        try:
            result = remove_github_webhook(app, preferred_user=preferred_user, github_adapter=self.github_port)
        except Exception as e:
            self.log_manager.warning(
                f'Erro ao remover webhook do GitHub: {e}', category=LogCategory.GIT, progress=90
            )
            return

        if result.get('ok'):
            self.log_manager.info(
                f'Webhook do GitHub removido ({result.get("status")})', category=LogCategory.GIT, progress=90
            )
        else:
            self.log_manager.warning(
                f'Nao foi possivel remover o webhook do GitHub: {result.get("error", result.get("status"))}',
                category=LogCategory.GIT,
                progress=90,
            )

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

        failure = None
        try:
            delete_output, _command = delete_dokku_service(self.dokku_port, runtime, dokku_service_name)
            if dokku_output_failed(delete_output):
                failure = f'Deleção do serviço {dokku_service_name} retornou erro: {delete_output}'
            else:
                self.log_manager.success(
                    f'Serviço {dokku_service_name} removido do Dokku',
                    category=LogCategory.DATABASE,
                    progress=progress,
                )
        except Exception as e:
            failure = f'Erro ao deletar serviço {dokku_service_name}: {e}'

        if failure:
            self.log_manager.warning(failure, category=LogCategory.DATABASE, progress=progress)
            _notify_service_delete_failed(service, dokku_service_name, failure)

        service.soft_delete(deleted_by_id=deleted_by_id)
