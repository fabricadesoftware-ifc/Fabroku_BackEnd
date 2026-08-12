"""Thin Celery tasks that wire real adapters to the use cases.

Each task's only job is: fetch the App for logging, build real adapters, and
call `.execute()`. All business logic lives in `applications/use_cases/`.

`core/apps/serializers.py`/`views.py`/`core/adapters/utils/git_webhook.py`
dispatch these directly (Fase 4.5). The legacy `CreateAppMixin`/`DeleteAppMixin`/
`RedeployAppMixin`/`UpdateAppMixin`/`ManageAppMixin`/`RunCommandMixin`/
`RunDataMixin`/`ProcessScaleMixin` classes they replaced have been removed;
`InteractiveRunMixin` remains (no use case equivalent yet — ADJUSTS_REFACTOR.md
Fase E).
"""
from celery import shared_task

from applications.models import App
from applications.use_cases.create_app import CreateAppCommand, CreateAppUseCase
from applications.use_cases.delete_app import DeleteAppCommand, DeleteAppUseCase
from applications.use_cases.deploy_app import DeployAppCommand, DeployAppUseCase
from applications.use_cases.manage_app import ManageAppCommand, ManageAppUseCase
from applications.use_cases.run_command import RunCommandCommand, RunCommandUseCase
from applications.use_cases.run_data import RunDataUseCase, RunDumpdataCommand, RunLoaddataCommand, RunMigrateCommand
from applications.use_cases.scale_processes import ScaleProcessesCommand, ScaleProcessesUseCase
from applications.use_cases.update_app import UpdateAppCommand, UpdateAppUseCase
from infrastructure.adapters.dokku import DokkuAdapter
from infrastructure.adapters.github import GitHubAdapter
from observability.models import AppLogManager


@shared_task(bind=True)
def create_app_task(self, app_id: int, user_id: int, env_vars: dict | None = None) -> dict:
    """Provision an already-registered App in Dokku via CreateAppUseCase."""
    app = App.objects.get(id=app_id)
    log_manager = AppLogManager(app, self.request.id)

    use_case = CreateAppUseCase(
        dokku_port=DokkuAdapter(),
        github_port=GitHubAdapter(),
        log_manager=log_manager,
    )
    result = use_case.execute(
        CreateAppCommand(app_id=app_id, user_id=user_id, env_vars=env_vars, task_id=self.request.id)
    )
    return {'status': result.status, 'app_id': result.app_id}


@shared_task(bind=True)
def deploy_app_task(self, app_id: int, commit: str | None = None, requested_by_id: int | None = None) -> dict:
    """Redeploy an already-provisioned App via DeployAppUseCase."""
    app = App.objects.get(id=app_id)
    log_manager = AppLogManager(app, self.request.id)

    use_case = DeployAppUseCase(
        dokku_port=DokkuAdapter(),
        github_port=GitHubAdapter(),
        log_manager=log_manager,
    )
    result = use_case.execute(
        DeployAppCommand(app_id=app_id, task_id=self.request.id, commit_sha=commit, user_id=requested_by_id)
    )
    return {'status': 'success', 'app_id': result.app_id, 'commit': result.commit_sha}


@shared_task(bind=True)
def update_app_task(
    self, app_id: int, name: str | None = None, git: str | None = None, env_vars: dict | None = None
) -> dict:
    """Rename/reconfigure an already-provisioned App via UpdateAppUseCase."""
    use_case = UpdateAppUseCase(dokku_port=DokkuAdapter())
    result = use_case.execute(
        UpdateAppCommand(app_id=app_id, task_id=self.request.id, name=name, git_url=git, env_vars=env_vars)
    )
    return {'status': 'updated', 'app_id': result.app_id}


@shared_task(bind=True)
def manage_app_task(self, app_id: int, action: str) -> dict:
    """Start/stop/restart an already-provisioned App via ManageAppUseCase."""
    app = App.objects.get(id=app_id)
    log_manager = AppLogManager(app, self.request.id)

    use_case = ManageAppUseCase(dokku_port=DokkuAdapter(), log_manager=log_manager)
    result = use_case.execute(ManageAppCommand(app_id=app_id, action=action, task_id=self.request.id))
    return {'status': 'success', 'action': result.action, 'app_id': result.app_id, 'output': result.output}


@shared_task(bind=True)
def delete_app_task(self, app_id: int, deleted_by_id: int | None = None) -> dict:
    """Delete an App and its linked services via DeleteAppUseCase."""
    app = App.objects.get(id=app_id)
    log_manager = AppLogManager(app, self.request.id)

    use_case = DeleteAppUseCase(dokku_port=DokkuAdapter(), log_manager=log_manager)
    result = use_case.execute(
        DeleteAppCommand(app_id=app_id, task_id=self.request.id, deleted_by_id=deleted_by_id)
    )
    return {'status': 'deleted', 'app_id': result.app_id, 'dokku_app': result.dokku_app_name}


@shared_task(bind=True)
def run_command_task(self, app_id: int, command: str) -> dict:
    """Run a whitelisted one-off command inside an App's container via RunCommandUseCase."""
    app = App.objects.get(id=app_id)
    log_manager = AppLogManager(app, self.request.id)

    use_case = RunCommandUseCase(dokku_port=DokkuAdapter(), log_manager=log_manager)
    result = use_case.execute(RunCommandCommand(app_id=app_id, command=command, task_id=self.request.id))
    return {'status': 'success', 'app_id': result.app_id, 'command': result.command, 'lines': result.lines}


@shared_task(bind=True)
def scale_processes_task(self, app_id: int, processes: dict) -> dict:
    """Apply desired process-quantity scaling for an App via ScaleProcessesUseCase."""
    app = App.objects.get(id=app_id)
    log_manager = AppLogManager(app, self.request.id)

    use_case = ScaleProcessesUseCase(dokku_port=DokkuAdapter(), log_manager=log_manager)
    result = use_case.execute(ScaleProcessesCommand(app_id=app_id, processes=processes, task_id=self.request.id))
    return {
        'status': 'success',
        'message': 'Escala de processos aplicada com sucesso.',
        'app_id': result.app_id,
        'dokku_app': result.dokku_app_name,
        'processes': result.processes,
        'output': result.output,
    }


@shared_task(bind=True)
def run_migrate_task(self, app_id: int, manage_path: str, noinput: bool, user_id: int) -> dict:
    """Run `manage.py migrate` inside an App's container via RunDataUseCase."""
    app = App.objects.get(id=app_id)
    log_manager = AppLogManager(app, self.request.id)

    use_case = RunDataUseCase(dokku_port=DokkuAdapter(), log_manager=log_manager)
    result = use_case.execute_migrate(
        RunMigrateCommand(app_id=app_id, manage_path=manage_path, noinput=noinput, task_id=self.request.id)
    )
    return {'status': 'success', 'app_id': result.app_id, 'command': result.command}


@shared_task(bind=True)
def run_loaddata_task(self, app_id: int, fixture_path: str, manage_path: str, user_id: int) -> dict:
    """Run `manage.py loaddata` inside an App's container via RunDataUseCase."""
    app = App.objects.get(id=app_id)
    log_manager = AppLogManager(app, self.request.id)

    use_case = RunDataUseCase(dokku_port=DokkuAdapter(), log_manager=log_manager)
    result = use_case.execute_loaddata(
        RunLoaddataCommand(
            app_id=app_id, fixture_path=fixture_path, manage_path=manage_path, task_id=self.request.id
        )
    )
    return {'status': 'success', 'app_id': result.app_id, 'command': result.command}


@shared_task(bind=True)
def run_dumpdata_task(  # noqa: PLR0913, PLR0917
    self, app_id: int, manage_path: str, dump_args: list[str], output_filename: str, user_id: int
) -> dict:
    """Run `manage.py dumpdata` inside an App's container via RunDataUseCase."""
    app = App.objects.get(id=app_id)
    log_manager = AppLogManager(app, self.request.id)

    use_case = RunDataUseCase(dokku_port=DokkuAdapter(), log_manager=log_manager)
    result = use_case.execute_dumpdata(
        RunDumpdataCommand(
            app_id=app_id,
            manage_path=manage_path,
            dump_args=dump_args,
            output_filename=output_filename,
            user_id=user_id,
            task_id=self.request.id,
        )
    )
    return {'status': 'success', 'app_id': result.app_id, 'artifact_id': result.artifact_id}
