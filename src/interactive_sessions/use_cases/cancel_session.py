"""CancelSessionUseCase: request cancellation of an interactive session.

Ports `AppViewSet.cancel_interactive_session` (`core/apps/views.py`)
faithfully: check the session belongs to the requesting app/user, then call
`core.apps.mixins.apps.interactive_run.request_interactive_session_cancel`
directly — pure DB logic, no adapter dependency. That function is already
idempotent for sessions in a terminal status, so this use case doesn't
reimplement that check.

Same ownership-check shape as `AnswerPromptUseCase`: "session not found for
this app/user" becomes `ApplicationDomainError` instead of a 404 response.
"""
from dataclasses import dataclass

from applications.domain.exceptions import ApplicationDomainError
from core.apps.mixins.apps.interactive_run import request_interactive_session_cancel
from interactive_sessions.models import InteractiveRunSession


@dataclass(frozen=True)
class CancelSessionCommand:
    app_id: int
    user_id: int
    session_id: str


@dataclass(frozen=True)
class SessionCancelRequested:
    session_id: str
    status: str


class CancelSessionUseCase:
    """Request cancellation of a pending/running interactive session."""

    def execute(self, cmd: CancelSessionCommand) -> SessionCancelRequested:
        exists = InteractiveRunSession.objects.filter(
            id=cmd.session_id, app_id=cmd.app_id, created_by_id=cmd.user_id
        ).exists()
        if not exists:
            raise ApplicationDomainError('Sessao interativa nao encontrada.')

        session = request_interactive_session_cancel(cmd.session_id)
        return SessionCancelRequested(session_id=str(session.id), status=session.status)
