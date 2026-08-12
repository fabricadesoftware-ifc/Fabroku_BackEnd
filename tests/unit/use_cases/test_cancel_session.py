"""Unit tests for CancelSessionUseCase (no SSH)."""
from datetime import timedelta

import pytest
from django.utils import timezone

from applications.domain.exceptions import ApplicationDomainError
from interactive_sessions.models import InteractiveRunCommandKind, InteractiveRunSession, InteractiveRunSessionStatus
from interactive_sessions.use_cases.cancel_session import (
    CancelSessionCommand,
    CancelSessionUseCase,
    SessionCancelRequested,
)
from tests.factories.models import AppFactory, ProjectFactory, UserFactory

pytestmark = pytest.mark.django_db


def make_session(app, user, *, status):
    now = timezone.now()
    return InteractiveRunSession.objects.create(
        app=app,
        created_by=user,
        command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
        status=status,
        expires_at=now + timedelta(minutes=5),
        last_activity_at=now,
    )


def test_cancel_running_session_requests_cancellation():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    user = UserFactory()
    session = make_session(app, user, status=InteractiveRunSessionStatus.RUNNING)
    use_case = CancelSessionUseCase()

    result = use_case.execute(CancelSessionCommand(app_id=app.id, user_id=user.id, session_id=str(session.id)))

    assert isinstance(result, SessionCancelRequested)
    session.refresh_from_db()
    assert session.cancel_requested is True


def test_cancel_already_terminal_session_is_idempotent():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    user = UserFactory()
    session = make_session(app, user, status=InteractiveRunSessionStatus.COMPLETED)
    use_case = CancelSessionUseCase()

    result = use_case.execute(CancelSessionCommand(app_id=app.id, user_id=user.id, session_id=str(session.id)))

    assert result.status == InteractiveRunSessionStatus.COMPLETED
    session.refresh_from_db()
    assert session.cancel_requested is False


def test_cancel_for_other_users_session_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    owner = UserFactory()
    other_user = UserFactory()
    session = make_session(app, owner, status=InteractiveRunSessionStatus.RUNNING)
    use_case = CancelSessionUseCase()

    with pytest.raises(ApplicationDomainError):
        use_case.execute(CancelSessionCommand(app_id=app.id, user_id=other_user.id, session_id=str(session.id)))
