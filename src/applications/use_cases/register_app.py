"""RegisterAppUseCase: enforce quota/name-conflict rules and create the App row.

This is where `AppLimitExceeded`/`AppNameConflict` (domain/exceptions.py) actually
belong. Before this use case existed, nothing in the codebase raised either of
them: the quota check lived inline in `AppSerializer.create()` as a plain DRF
`serializers.ValidationError`, and name conflicts were never pre-checked at all —
they surfaced as an unhandled `IntegrityError` from the model's unique constraint,
which DRF's default exception handler doesn't understand, producing a raw 500.

Provisioning the App in Dokku is a separate concern, handled later (once this
use case's App row exists) by `CreateAppUseCase` / `create_app_task`.
"""
from dataclasses import dataclass

from applications.domain.exceptions import AppLimitExceeded, AppNameConflict
from applications.models import App, AppStatus
from identity.models import User
from projects.models import Project


@dataclass(frozen=True)
class RegisterAppCommand:
    user_id: int
    project_id: str
    app_name: str
    git_url: str
    git_branch: str = 'main'
    env_vars: dict[str, str] | None = None
    name_dokku: str | None = None


class RegisterAppUseCase:
    """Validate quota/name-conflict rules and create the App row (status=STARTING)."""

    def execute(self, cmd: RegisterAppCommand) -> App:
        user = User.objects.get(id=cmd.user_id)
        project = Project.objects.get(id=cmd.project_id)

        if not user.can_create_app():
            raise AppLimitExceeded(current=user.apps_count, limit=user.max_apps)

        if App.objects.filter(name__iexact=cmd.app_name, deleted_at__isnull=True).exists():
            raise AppNameConflict(cmd.app_name)

        return App.objects.create(
            name=cmd.app_name,
            name_dokku=cmd.name_dokku,
            git=cmd.git_url,
            branch=cmd.git_branch,
            project=project,
            status=AppStatus.STARTING,
            variables=cmd.env_vars or {},
        )
