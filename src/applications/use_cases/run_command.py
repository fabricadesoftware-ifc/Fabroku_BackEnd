"""RunCommandUseCase: business logic for executing a whitelisted command inside
an app's container.

Ports `core/apps/mixins/apps/run_command.py` (`RunCommandMixin.run_command`)
faithfully: whitelist check, warm up linked Postgres services (with the same
stuck-container/conflict recovery the legacy code has), run the command
streaming, retry once on a transient "container not running" error, then
record success/failure on the App row.

Reuses `is_command_allowed`/`ALLOWED_COMMANDS`/`ALLOWED_PREFIXES` from the
legacy module directly — the whitelist is security-sensitive and must not
drift between two copies. `core/apps/views.py` already imports these the
same way.

Deviations from the legacy task, consistent with every other Fase 2/4 use
case: no `task.update_state(...)` calls, and the legacy silent
`return {'status': 'error', ...}` for "app not found" / "no name_dokku" /
"command not allowed" now raise `AppNotFound/DeploymentFailed/CommandNotAllowed`
instead.
"""
import time
from dataclasses import dataclass

from applications.domain.exceptions import ApplicationDomainError, DeploymentFailed
from applications.models import App
from applications.ports.i_dokku import IDokkuPort
from core.apps.mixins.apps.run_command import is_command_allowed
from observability.models import AppLogManager, LogCategory
from service_mgmt.models import Service
from service_mgmt.service_types import is_postgres_service_type

_ERROR_MARKERS = (
    '[error]',
    '[ssh error]',
    'failed to execute command',
    'traceback (most recent call last):',
    'commanderror',
    ' error:',
    'cannot link to a non running container',
)

_MAX_ATTEMPTS = 2


class CommandNotAllowed(ApplicationDomainError):
    """The requested command isn't on the run-command whitelist."""

    def __init__(self, command: str):
        self.command = command
        super().__init__(f'Comando não permitido: {command}')


def _command_output_has_error(output: str) -> bool:
    normalized = (output or '').lower()
    return any(marker in normalized for marker in _ERROR_MARKERS)


@dataclass(frozen=True)
class RunCommandCommand:
    app_id: int
    command: str
    task_id: str | None = None


@dataclass(frozen=True)
class CommandRun:
    app_id: int
    command: str
    output: str
    lines: int


class RunCommandUseCase:
    """Run a whitelisted one-off command inside an app's container."""

    def __init__(self, dokku_port: IDokkuPort, log_manager: AppLogManager):
        self.dokku_port = dokku_port
        self.log_manager = log_manager

    def execute(self, cmd: RunCommandCommand) -> CommandRun:
        app = App.objects.get(id=cmd.app_id, deleted_at__isnull=True)

        if not app.name_dokku:
            raise DeploymentFailed(reason='App sem name_dokku configurado', step='validate')

        if not is_command_allowed(cmd.command):
            raise CommandNotAllowed(cmd.command)

        app.task_id = cmd.task_id
        app.save(update_fields=['task_id'])

        try:
            linked_services = self._warm_up_linked_databases(app)

            self.log_manager.info(f'Executando comando: {cmd.command}', category=LogCategory.SYSTEM, progress=10)

            full_output, line_count = self._run_with_retry(app, cmd.command, linked_services)

            if _command_output_has_error(full_output):
                error_output = full_output.strip() or f'Falha ao executar comando: {cmd.command}'
                app.error_type = 'CommandExecutionError'
                app.error_details = error_output
                app.save(update_fields=['error_type', 'error_details'])
                self.log_manager.error(
                    f'Comando finalizado com erro: {cmd.command}',
                    category=LogCategory.SYSTEM,
                    progress=100,
                    metadata={'command': cmd.command, 'output': error_output[:2000]},
                )
                raise RuntimeError(error_output)

            app.error_type = None
            app.error_details = None
            app.save(update_fields=['error_type', 'error_details'])

            self.log_manager.success(
                f'Comando executado com sucesso! ({line_count} linhas de output)',
                category=LogCategory.SYSTEM,
                progress=100,
            )

            return CommandRun(app_id=app.id, command=cmd.command, output=full_output, lines=line_count)

        except Exception as e:
            if not app.error_details:
                app.error_type = type(e).__name__
                app.error_details = str(e)
                app.save(update_fields=['error_type', 'error_details'])
            self.log_manager.error(
                f'Erro ao executar comando: {e}',
                category=LogCategory.SYSTEM,
                metadata={'error_type': type(e).__name__, 'command': cmd.command},
            )
            raise

    def _warm_up_linked_databases(self, app: App) -> list[Service]:
        linked_services = list(Service.objects.filter(app=app, deleted_at__isnull=True))
        for svc in linked_services:
            if svc.container_name and is_postgres_service_type(svc.service_type):
                self._start_database_with_recovery(svc.container_name)
                time.sleep(3)
        return linked_services

    def _start_database_with_recovery(self, container_name: str) -> str:
        out = self.dokku_port.start_database(container_name)
        out_lower = out.lower()
        if 'failed' not in out_lower:
            return out

        if 'sethostname' in out_lower or 'invalid argument' in out_lower:
            self.log_manager.info(
                'Container travado por hostname invalido (runc), removendo...',
                category=LogCategory.SYSTEM,
                progress=5,
            )
            self.dokku_port.remove_postgres_container(container_name)
            time.sleep(2)
            out = self.dokku_port.start_database(container_name)
        elif 'already in use' in out_lower or 'conflict' in out_lower:
            self.log_manager.info(
                'Container em conflito, tentando postgres:stop antes de start...',
                category=LogCategory.SYSTEM,
                progress=5,
            )
            self.dokku_port.stop_database(container_name)
            time.sleep(2)
            out = self.dokku_port.start_database(container_name)

        if 'failed' in out.lower():
            msg = f'postgres:start {container_name} retornou erro: {out}'
            if 'sethostname' in out.lower():
                msg += ' Remova o banco e crie um novo (nome curto compativel com runc).'
            self.log_manager.warning(msg, category=LogCategory.SYSTEM, progress=5)

        return out

    def _run_with_retry(self, app: App, command: str, linked_services: list[Service]) -> tuple[str, int]:
        full_output = ''
        line_count = 0

        for attempt in range(_MAX_ATTEMPTS):
            lines: list[str] = []

            for line in self.dokku_port.run_in_app_streaming(app.name_dokku, command):
                if not line.strip():
                    continue
                lines.append(line)
                progress = min(10 + (len(lines) * 2), 90)
                self.log_manager.dokku(line, category=LogCategory.SYSTEM, progress=int(progress))

            full_output = '\n'.join(lines)
            line_count = len(lines)

            if attempt < _MAX_ATTEMPTS - 1 and 'cannot link to a non running container' in full_output.lower():
                self.log_manager.warning(
                    'Container do banco pode nao estar pronto. Tentando stop+start e tentando novamente...',
                    category=LogCategory.SYSTEM,
                    progress=10,
                )
                for svc in linked_services:
                    if svc.container_name and is_postgres_service_type(svc.service_type):
                        self.dokku_port.stop_database(svc.container_name)
                        time.sleep(2)
                        self.dokku_port.start_database(svc.container_name)
                time.sleep(5)
                continue

            break

        return full_output, line_count
