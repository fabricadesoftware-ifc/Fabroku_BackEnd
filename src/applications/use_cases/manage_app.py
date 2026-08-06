"""ManageAppUseCase: business logic for starting/stopping/restarting an application.

Ports `core/apps/mixins/apps/manage_app.py` (`ManageAppMixin.manage_app_task`)
faithfully: warm up linked Postgres services before start/restart, run the
Dokku action, update status.

Same deviations as the other Fase 2/4 use cases: no `task.update_state(...)`
calls, and the legacy silent `return {'status': 'error', ...}` for a missing
`name_dokku` now raises `DeploymentFailed` instead.
"""
from dataclasses import dataclass
from typing import Literal

from applications.domain.exceptions import DeploymentFailed
from applications.models import App, AppStatus
from applications.ports.i_dokku import IDokkuPort
from observability.models import AppLogManager, LogCategory
from service_mgmt.models import Service
from service_mgmt.service_types import is_postgres_service_type

AppAction = Literal['start', 'stop', 'restart']

_ACTION_MESSAGES: dict[AppAction, tuple[str, str, str]] = {
    'start': ('Iniciando', 'iniciada', AppStatus.RUNNING),
    'stop': ('Parando', 'parada', AppStatus.STOPPED),
    'restart': ('Reiniciando', 'reiniciada', AppStatus.RUNNING),
}


@dataclass(frozen=True)
class ManageAppCommand:
    app_id: int
    action: AppAction
    task_id: str | None = None


@dataclass(frozen=True)
class AppManaged:
    app_id: int
    action: AppAction
    dokku_app_name: str
    output: str


class ManageAppUseCase:
    """Start, stop, or restart an already-provisioned App."""

    def __init__(self, dokku_port: IDokkuPort, log_manager: AppLogManager):
        self.dokku_port = dokku_port
        self.log_manager = log_manager

    def execute(self, cmd: ManageAppCommand) -> AppManaged:
        app = App.objects.get(id=cmd.app_id, deleted_at__isnull=True)
        msg_progress, msg_done, final_status = _ACTION_MESSAGES[cmd.action]

        app.task_id = cmd.task_id
        app.save(update_fields=['task_id'])

        self.log_manager.info(f'{msg_progress} aplicação...', category=LogCategory.DEPLOY, progress=10)

        dokku_app_name = app.name_dokku
        if not dokku_app_name:
            self.log_manager.error('App não tem name_dokku configurado', category=LogCategory.DEPLOY)
            raise DeploymentFailed(reason='App não tem name_dokku configurado', step='validate')

        try:
            if cmd.action in ('start', 'restart'):
                self._start_linked_databases(app)

            if cmd.action == 'start':
                output = self.dokku_port.start_app(dokku_app_name)
            elif cmd.action == 'stop':
                output = self.dokku_port.stop_app(dokku_app_name)
            else:
                output = self.dokku_port.restart_app(dokku_app_name)

            self.log_manager.dokku(output, category=LogCategory.DEPLOY, progress=80)

            app.status = final_status
            app.save(update_fields=['status'])

            self.log_manager.success(
                f'Aplicação {msg_done} com sucesso!', category=LogCategory.DEPLOY, progress=100
            )

            return AppManaged(app_id=app.id, action=cmd.action, dokku_app_name=dokku_app_name, output=output)

        except Exception as e:
            self.log_manager.error(f'Erro ao {cmd.action} aplicação: {e}', category=LogCategory.DEPLOY)
            app.status = AppStatus.ERROR
            app.save(update_fields=['status'])
            raise

    def _start_linked_databases(self, app: App) -> None:
        """Best-effort warm-up of linked Postgres services before start/restart."""
        for svc in Service.objects.filter(app=app, deleted_at__isnull=True):
            if svc.container_name and is_postgres_service_type(svc.service_type):
                try:
                    self.dokku_port.start_database(svc.container_name)
                except Exception:
                    pass
