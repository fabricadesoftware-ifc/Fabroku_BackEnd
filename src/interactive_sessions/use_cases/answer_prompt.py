"""AnswerPromptUseCase: submit an answer to an interactive session's current prompt.

Ports `AppViewSet.answer_interactive_session` (`core/apps/views.py`)
faithfully: check the session belongs to the requesting app/user (same
unlocked existence check the view does before delegating), then call
`core.apps.mixins.apps.interactive_run.submit_interactive_session_answer`
directly — it's already pure DB logic (`select_for_update` + validation),
nothing to port.

The legacy view/consumer's `except ValueError` (mapped to HTTP 409) becomes
`InteractiveSessionAnswerRejected`, and "session not found for this app/user"
becomes `ApplicationDomainError`, consistent with the domain-exception
discipline used by every other Fase 4 use case.
"""
from dataclasses import dataclass

from applications.domain.exceptions import ApplicationDomainError
from core.apps.mixins.apps.interactive_run import submit_interactive_session_answer
from interactive_sessions.models import InteractiveRunSession


class InteractiveSessionAnswerRejected(ApplicationDomainError):
    """The session isn't currently awaiting this prompt (wrong state or already answered)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class AnswerPromptCommand:
    app_id: int
    user_id: int
    session_id: str
    prompt_id: str
    value: str


@dataclass(frozen=True)
class PromptAnswered:
    session_id: str
    status: str


class AnswerPromptUseCase:
    """Submit an answer to an interactive session's current prompt."""

    def execute(self, cmd: AnswerPromptCommand) -> PromptAnswered:
        exists = InteractiveRunSession.objects.filter(
            id=cmd.session_id, app_id=cmd.app_id, created_by_id=cmd.user_id
        ).exists()
        if not exists:
            raise ApplicationDomainError('Sessao interativa nao encontrada.')

        try:
            session = submit_interactive_session_answer(cmd.session_id, cmd.prompt_id, cmd.value)
        except ValueError as e:
            raise InteractiveSessionAnswerRejected(str(e)) from e

        return PromptAnswered(session_id=str(session.id), status=session.status)
