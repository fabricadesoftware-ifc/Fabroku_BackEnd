"""ScaleProcessesUseCase: business logic for scaling an application's Dokku processes.

Ports `core/apps/mixins/apps/process_scale.py` (`ProcessScaleMixin.scale_app_processes`)
faithfully: validate the requested process quantities, run `dokku ps:scale`, persist the
desired quantities, and sync `AppProcessScale` rows from Dokku's stdout. Reuses the pure
helper functions in `applications/process_scale.py` as-is (not duplicated).

Same deviation as `ManageAppUseCase`/other Fase 4 use cases: no `task.update_state(...)`
calls, and the legacy silent `return {'status': 'error', ...}` for "app not found" /
missing `name_dokku` now raise `AppNotFound`/`DeploymentFailed` instead of being swallowed.
"""
from dataclasses import dataclass

from applications.domain.exceptions import AppNotFound, DeploymentFailed
from applications.models import App
from applications.ports.i_dokku import IDokkuPort
from applications.process_scale import (
    dokku_scale_output_failed,
    save_desired_process_quantities,
    sync_app_process_scales_from_dokku,
    validate_process_quantities,
)
from observability.models import AppLogManager, LogCategory


@dataclass(frozen=True)
class ScaleProcessesCommand:
    app_id: int
    processes: dict
    task_id: str | None = None


@dataclass(frozen=True)
class ProcessesScaled:
    app_id: int
    dokku_app_name: str
    processes: dict[str, int]
    output: str


class ScaleProcessesUseCase:
    """Apply desired process-quantity scaling for an already-provisioned App."""

    def __init__(self, dokku_port: IDokkuPort, log_manager: AppLogManager):
        self.dokku_port = dokku_port
        self.log_manager = log_manager

    def execute(self, cmd: ScaleProcessesCommand) -> ProcessesScaled:
        try:
            app = App.objects.get(id=cmd.app_id, deleted_at__isnull=True)
        except App.DoesNotExist:
            raise AppNotFound(cmd.app_id) from None

        app.task_id = cmd.task_id
        app.save(update_fields=['task_id'])

        self.log_manager.info('Aplicando escala de processos...', category=LogCategory.DEPLOY, progress=10)

        if not app.name_dokku:
            self.log_manager.error('App nao tem name_dokku configurado', category=LogCategory.DEPLOY)
            raise DeploymentFailed(reason='App nao tem name_dokku configurado', step='validate')

        validated_processes = validate_process_quantities(cmd.processes)
        command = 'dokku ps:scale ' + app.name_dokku + ' ' + ' '.join(
            f'{process_name}={quantity}' for process_name, quantity in validated_processes.items()
        )

        output = self.dokku_port.ps_scale(app.name_dokku, validated_processes)
        self.log_manager.dokku(output, command=command, category=LogCategory.DEPLOY, progress=75)

        if dokku_scale_output_failed(output):
            self.log_manager.error(
                'Falha ao aplicar escala de processos.', category=LogCategory.DEPLOY, progress=100
            )
            raise DeploymentFailed(reason=output, step='scale')

        save_desired_process_quantities(app, validated_processes)
        sync_app_process_scales_from_dokku(app, self.dokku_port, output=output)

        self.log_manager.success(
            'Escala de processos aplicada com sucesso.', category=LogCategory.DEPLOY, progress=100
        )

        return ProcessesScaled(
            app_id=app.id,
            dokku_app_name=app.name_dokku,
            processes=validated_processes,
            output=output,
        )
