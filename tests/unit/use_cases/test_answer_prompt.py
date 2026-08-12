"""Unit tests for AnswerPromptUseCase (no SSH)."""
from datetime import timedelta

import pytest
from django.utils import timezone

from applications.domain.exceptions import ApplicationDomainError
from interactive_sessions.models import InteractiveRunCommandKind, InteractiveRunSession, InteractiveRunSessionStatus
from interactive_sessions.use_cases.answer_prompt import (
    AnswerPromptCommand,
    AnswerPromptUseCase,
    InteractiveSessionAnswerRejected,
    PromptAnswered,
)
from tests.factories.models import AppFactory, ProjectFactory, UserFactory

pytestmark = pytest.mark.django_db


def make_session(app, user, *, status, awaiting_prompt_id=None):
    now = timezone.now()
    return InteractiveRunSession.objects.create(
        app=app,
        created_by=user,
        command_kind=InteractiveRunCommandKind.DJANGO_CREATESUPERUSER,
        status=status,
        awaiting_prompt_id=awaiting_prompt_id,
        expires_at=now + timedelta(minutes=5),
        last_activity_at=now,
    )


def test_answer_prompt_success():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    user = UserFactory()
    session = make_session(app, user, status=InteractiveRunSessionStatus.AWAITING_INPUT, awaiting_prompt_id='email-1')
    use_case = AnswerPromptUseCase()

    result = use_case.execute(
        AnswerPromptCommand(
            app_id=app.id, user_id=user.id, session_id=str(session.id), prompt_id='email-1', value='a@b.com'
        )
    )

    assert isinstance(result, PromptAnswered)
    session.refresh_from_db()
    assert session.pending_answer_ciphertext is not None


def test_answer_prompt_wrong_state_rejected():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    user = UserFactory()
    session = make_session(app, user, status=InteractiveRunSessionStatus.RUNNING)
    use_case = AnswerPromptUseCase()

    with pytest.raises(InteractiveSessionAnswerRejected):
        use_case.execute(
            AnswerPromptCommand(
                app_id=app.id, user_id=user.id, session_id=str(session.id), prompt_id='email-1', value='x'
            )
        )


def test_answer_prompt_wrong_prompt_id_rejected():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    user = UserFactory()
    session = make_session(app, user, status=InteractiveRunSessionStatus.AWAITING_INPUT, awaiting_prompt_id='email-1')
    use_case = AnswerPromptUseCase()

    with pytest.raises(InteractiveSessionAnswerRejected):
        use_case.execute(
            AnswerPromptCommand(
                app_id=app.id, user_id=user.id, session_id=str(session.id), prompt_id='name-1', value='x'
            )
        )


def test_answer_prompt_for_other_users_session_raises():
    project = ProjectFactory()
    app = AppFactory(project=project, name_dokku='my-app')
    owner = UserFactory()
    other_user = UserFactory()
    session = make_session(app, owner, status=InteractiveRunSessionStatus.AWAITING_INPUT, awaiting_prompt_id='email-1')
    use_case = AnswerPromptUseCase()

    with pytest.raises(ApplicationDomainError):
        use_case.execute(
            AnswerPromptCommand(
                app_id=app.id, user_id=other_user.id, session_id=str(session.id), prompt_id='email-1', value='x'
            )
        )
