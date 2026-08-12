"""UpdateAppUseCase: business logic for renaming/reconfiguring an existing application.

Ports `core/apps/mixins/apps/update_app.py` (`UpdateAppMixin.update_app`) faithfully:
rename in Dokku, update the git remote, update env vars — each only if changed.

Same deviations as CreateAppUseCase/DeployAppUseCase: no `task.update_state(...)`
calls (Celery-specific, not the use case's concern), and the legacy silent
`return {'status': 'error', ...}` for a missing `name_dokku` now raises
`DeploymentFailed` instead — consistent with DeployAppUseCase's fix for the
same failure shape.
"""
from dataclasses import dataclass

from applications.domain.exceptions import DeploymentFailed
from applications.models import App, AppStatus
from applications.ports.i_dokku import IDokkuPort
from core.apps.utils import slugify_dokku


@dataclass(frozen=True)
class UpdateAppCommand:
    app_id: int
    task_id: str | None = None
    name: str | None = None
    git_url: str | None = None
    env_vars: dict[str, str] | None = None


@dataclass(frozen=True)
class AppUpdated:
    app_id: int
    dokku_app_name: str


class UpdateAppUseCase:
    """Rename/reconfigure an already-provisioned App, applying only the fields that changed."""

    def __init__(self, dokku_port: IDokkuPort):
        self.dokku_port = dokku_port

    def execute(self, cmd: UpdateAppCommand) -> AppUpdated:
        app = App.objects.get(id=cmd.app_id, deleted_at__isnull=True)

        if not app.name_dokku:
            raise DeploymentFailed(reason='App não tem name_dokku configurado', step='validate')

        app.status = AppStatus.DEPLOYING
        app.task_id = cmd.task_id
        app.save(update_fields=['status', 'task_id'])

        if cmd.name and app.name != cmd.name:
            new_dokku_name = slugify_dokku(cmd.name)
            self.dokku_port.rename_app(app.name_dokku, new_dokku_name)
            app.name = cmd.name
            app.name_dokku = new_dokku_name
            app.save()

        if cmd.git_url and app.git != cmd.git_url:
            self.dokku_port.set_git_remote(app.name_dokku, cmd.git_url)
            app.git = cmd.git_url
            app.save()

        if cmd.env_vars is not None:
            self.dokku_port.set_config(app.name_dokku, cmd.env_vars)
            app.variables = cmd.env_vars
            app.save()

        app.status = AppStatus.RUNNING
        app.save()

        return AppUpdated(app_id=app.id, dokku_app_name=app.name_dokku)
