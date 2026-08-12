"""RunDataUseCase: business logic for Django data-management commands
(migrate/loaddata/dumpdata) inside an app's container.

Ports `core/apps/mixins/apps/run_data.py` (`RunDataMixin`) faithfully — reuses
its command-builder/validator functions directly (`build_migrate_command`,
`build_loaddata_command`, `build_dumpdata_command`, `command_output_failed`,
`cleanup_expired_run_artifacts`, `get_run_artifact_expires_at`): they're pure
functions with no adapter dependency, so there's nothing to port, just reuse.

Deviations from the legacy tasks, consistent with the rest of Fase 2/4: no
`task.update_state(...)` calls, and `App.DoesNotExist` is left to propagate
naturally instead of `run_migrate`'s legacy (and here, inconsistent-with-its-
siblings) `raise RuntimeError(...) from e` wrapping.
"""
from dataclasses import dataclass

from django.conf import settings

from applications.domain.exceptions import DeploymentFailed
from applications.models import App, AppRunArtifact, AppRunArtifactKind
from applications.ports.i_dokku import IDokkuPort
from core.apps.mixins.apps.run_data import (
    build_dumpdata_command,
    build_loaddata_command,
    build_migrate_command,
    cleanup_expired_run_artifacts,
    command_output_failed,
    get_run_artifact_expires_at,
)
from observability.models import AppLogManager, LogCategory


@dataclass(frozen=True)
class RunMigrateCommand:
    app_id: int
    manage_path: str
    noinput: bool = False
    task_id: str | None = None


@dataclass(frozen=True)
class RunLoaddataCommand:
    app_id: int
    fixture_path: str
    manage_path: str
    task_id: str | None = None


@dataclass(frozen=True)
class RunDumpdataCommand:
    app_id: int
    manage_path: str
    dump_args: list[str]
    output_filename: str
    user_id: int
    task_id: str | None = None


@dataclass(frozen=True)
class DataCommandRun:
    app_id: int
    command: str
    output: str


@dataclass(frozen=True)
class DumpdataRun:
    app_id: int
    command: str
    artifact_id: str
    filename: str
    size: int


class RunDataUseCase:
    """Run Django management commands (migrate/loaddata/dumpdata) inside an app's container."""

    def __init__(self, dokku_port: IDokkuPort, log_manager: AppLogManager):
        self.dokku_port = dokku_port
        self.log_manager = log_manager

    def execute_migrate(self, cmd: RunMigrateCommand) -> DataCommandRun:
        app = self._get_app_with_dokku_name(cmd.app_id, cmd.task_id)
        command = build_migrate_command(cmd.manage_path, noinput=cmd.noinput)
        try:
            self.log_manager.info(
                'Executando migrations Django.',
                category=LogCategory.DATABASE,
                progress=10,
                metadata={'command': command, 'manage_path': cmd.manage_path, 'noinput': cmd.noinput},
            )
            output = self._run_and_check(
                app, command, action='migrate', error_type='MigrateExecutionError', log_lines=True
            )
            return DataCommandRun(app_id=app.id, command=command, output=output)
        except Exception as e:
            self._record_failure(app, command, action='migrate', error=e)
            raise
        finally:
            cleanup_expired_run_artifacts()

    def execute_loaddata(self, cmd: RunLoaddataCommand) -> DataCommandRun:
        app = self._get_app_with_dokku_name(cmd.app_id, cmd.task_id)
        command = build_loaddata_command(cmd.manage_path, cmd.fixture_path)
        try:
            self.log_manager.info(
                f'Executando loaddata com fixture {cmd.fixture_path}',
                category=LogCategory.DATABASE,
                progress=10,
                metadata={'command': command, 'fixture_path': cmd.fixture_path},
            )
            output = self._run_and_check(
                app, command, action='loaddata', error_type='LoaddataExecutionError', log_lines=True
            )
            return DataCommandRun(app_id=app.id, command=command, output=output)
        except Exception as e:
            self._record_failure(app, command, action='loaddata', error=e)
            raise
        finally:
            cleanup_expired_run_artifacts()

    def execute_dumpdata(self, cmd: RunDumpdataCommand) -> DumpdataRun:
        app = self._get_app_with_dokku_name(cmd.app_id, cmd.task_id)
        command = build_dumpdata_command(cmd.manage_path, cmd.dump_args)
        try:
            self.log_manager.info(
                f'Executando dumpdata para {cmd.output_filename}',
                category=LogCategory.DATABASE,
                progress=10,
                metadata={'command': command, 'filename': cmd.output_filename},
            )

            output = self.dokku_port.run_in_app(app.name_dokku, command)
            if command_output_failed(output):
                self._mark_error(app, 'DumpdataExecutionError', output[:4000])
                self.log_manager.error(
                    'dumpdata finalizado com erro.',
                    category=LogCategory.DATABASE,
                    progress=100,
                    metadata={'command': command},
                )
                raise RuntimeError(output)

            content = output.encode('utf-8')
            max_size = int(getattr(settings, 'CLI_RUN_ARTIFACT_MAX_BYTES', 50 * 1024 * 1024))
            if len(content) > max_size:
                raise RuntimeError(f'dumpdata excedeu o limite de {max_size} bytes.')

            artifact = AppRunArtifact.objects.create(
                app=app,
                created_by_id=cmd.user_id,
                kind=AppRunArtifactKind.DUMP_DATA_EXPORT,
                filename=cmd.output_filename,
                content_type='application/json',
                size=len(content),
                content=content,
                expires_at=get_run_artifact_expires_at(),
            )

            self._mark_success(app)
            self.log_manager.success(
                f'dumpdata gerado com sucesso ({len(content)} bytes).',
                category=LogCategory.DATABASE,
                progress=100,
                metadata={'artifact_id': str(artifact.id), 'filename': cmd.output_filename, 'size': len(content)},
            )

            return DumpdataRun(
                app_id=app.id,
                command=command,
                artifact_id=str(artifact.id),
                filename=artifact.filename,
                size=artifact.size,
            )
        except Exception as e:
            self._record_failure(app, command, action='dumpdata', error=e)
            raise
        finally:
            cleanup_expired_run_artifacts()

    def _get_app_with_dokku_name(self, app_id: int, task_id: str | None) -> App:
        app = App.objects.get(id=app_id, deleted_at__isnull=True)
        if not app.name_dokku:
            raise DeploymentFailed(reason='App sem name_dokku configurado', step='validate')
        app.task_id = task_id
        app.save(update_fields=['task_id'])
        return app

    def _run_and_check(self, app: App, command: str, *, action: str, error_type: str, log_lines: bool) -> str:
        output = self.dokku_port.run_in_app(app.name_dokku, command)

        if log_lines and output.strip():
            for line in output.splitlines()[:100]:
                self.log_manager.dokku(line, category=LogCategory.DATABASE, progress=60)

        if command_output_failed(output):
            self._mark_error(app, error_type, output[:4000])
            self.log_manager.error(
                f'{action} finalizado com erro.',
                category=LogCategory.DATABASE,
                progress=100,
                metadata={'command': command},
            )
            raise RuntimeError(output)

        self._mark_success(app)
        self.log_manager.success(f'{action} executado com sucesso.', category=LogCategory.DATABASE, progress=100)
        return output

    def _mark_error(self, app: App, error_type: str, error_details: str) -> None:
        app.error_type = error_type
        app.error_details = error_details
        app.save(update_fields=['error_type', 'error_details'])

    def _mark_success(self, app: App) -> None:
        app.error_type = None
        app.error_details = None
        app.save(update_fields=['error_type', 'error_details'])

    def _record_failure(self, app: App, command: str, *, action: str, error: Exception) -> None:
        if not app.error_details:
            app.error_type = type(error).__name__
            app.error_details = str(error)
            app.save(update_fields=['error_type', 'error_details'])
        self.log_manager.error(
            f'Erro ao executar {action}: {error}',
            category=LogCategory.DATABASE,
            metadata={'error_type': type(error).__name__, 'command': command},
        )
