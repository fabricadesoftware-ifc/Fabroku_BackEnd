"""Unit tests for StartInteractiveSessionUseCase (no SSH, no live runner process)."""
import pytest

from applications.domain.exceptions import ApplicationDomainError, DeploymentFailed
from interactive_sessions.interactive_runner import touch_interactive_runner
from interactive_sessions.models import InteractiveRunCommandKind, InteractiveRunSessionStatus
from interactive_sessions.use_cases.start_session import (
    InteractiveRunnerUnavailable,
    InteractiveSessionStarted,
    StartInteractiveSessionCommand,
    StartInteractiveSessionUseCase,
)
from tests.factories.models import AppFactory, ProjectFactory, ServiceFactory, UserFactory

pytestmark = pytest.mark.django_db


def make_use_case():
    return StartInteractiveSessionUseCase()


def test_start_createsuperuser_session_success():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    user = UserFactory()
    touch_interactive_runner('test-runner')
    use_case = make_use_case()

    result = use_case.execute(
        StartInteractiveSessionCommand(
            app_id=app.id, user_id=user.id, command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER
        )
    )

    assert isinstance(result, InteractiveSessionStarted)
    assert result.status == InteractiveRunSessionStatus.PENDING
    assert result.service_id is None


def test_start_postgres_connect_session_success():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    user = UserFactory()
    service = ServiceFactory(app=app, project=project, service_type='postgres', container_name='my-app-db-1')
    touch_interactive_runner('test-runner')
    use_case = make_use_case()

    result = use_case.execute(
        StartInteractiveSessionCommand(
            app_id=app.id, user_id=user.id, command_kind=InteractiveRunCommandKind.POSTGRES_CONNECT
        )
    )

    assert result.service_id == service.id


def test_start_session_without_live_runner_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    user = UserFactory()
    use_case = make_use_case()

    with pytest.raises(InteractiveRunnerUnavailable):
        use_case.execute(
            StartInteractiveSessionCommand(
                app_id=app.id, user_id=user.id, command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER
            )
        )


def test_start_session_without_name_dokku_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku=None)
    user = UserFactory()
    touch_interactive_runner('test-runner')
    use_case = make_use_case()

    with pytest.raises(DeploymentFailed):
        use_case.execute(
            StartInteractiveSessionCommand(
                app_id=app.id, user_id=user.id, command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER
            )
        )


def test_start_postgres_connect_session_without_service_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    user = UserFactory()
    touch_interactive_runner('test-runner')
    use_case = make_use_case()

    with pytest.raises(ApplicationDomainError):
        use_case.execute(
            StartInteractiveSessionCommand(
                app_id=app.id, user_id=user.id, command_kind=InteractiveRunCommandKind.POSTGRES_CONNECT
            )
        )
