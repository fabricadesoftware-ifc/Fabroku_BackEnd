"""StartInteractiveSessionUseCase: validate and persist a new interactive
session (Django createsuperuser / Postgres connect) for later execution.

Ports `AppViewSet.create_interactive_session` (`core/apps/views.py`)
faithfully: resolve the command driver, resolve/validate the target
(Postgres service or `manage.py` path), require a live `interactive` runner
process, then persist the `PENDING` session.

Deliberately does *not* call any `IDokkuPort` method and does not dispatch a
Celery task: the actual SSH execution (`execute_interactive_session` /
`InteractiveRunMixin.run_interactive_session`) is claimed later by the
dedicated `interactive` runner process (`interactive_sessions.interactive_runner`), not
started synchronously here — this use case's only job is validate + persist.
Porting that execution loop itself is out of scope for Fase 4.3 (it drives a
raw paramiko channel, not `IDokkuPort`'s single-shot methods; that split
would need its own `IDokkuPort` extension and is noted as follow-up work).

`get_interactive_driver`'s `ValueError` for an unsupported `command_kind` is
left to propagate naturally, same precedent as `get_service_runtime` in the
Fase 4.2 use cases. The Postgres-service resolution checks (ported from the
private `_resolve_postgres_connect_service` in `views.py`, so there's no
existing helper to reuse as-is) and the missing-runner check become
`ApplicationDomainError`/`InteractiveRunnerUnavailable` instead of the
legacy view's `ValueError`/503 response.
"""
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from applications.domain.exceptions import ApplicationDomainError, DeploymentFailed
from applications.models import App
from core.apps.mixins.apps.interactive_run import (
    cleanup_expired_interactive_sessions,
    get_interactive_driver,
    get_interactive_session_expires_at,
)
from core.apps.mixins.apps.run_data import validate_manage_path
from core.apps.mixins.services.service_env import postgres_service_types
from interactive_sessions.interactive_runner import has_live_interactive_runner
from interactive_sessions.models import InteractiveRunCommandKind, InteractiveRunSession, InteractiveRunSessionStatus
from service_mgmt.models import Service


class InteractiveRunnerUnavailable(ApplicationDomainError):
    """No live `interactive` runner process is available to claim the session."""

    def __init__(self):
        super().__init__(
            'Nenhum runner interativo esta ativo. Escale o processo interactive antes de abrir sessoes da CLI.'
        )


@dataclass(frozen=True)
class StartInteractiveSessionCommand:
    app_id: int
    user_id: int
    command_kind: str
    manage_path: str | None = None
    service_id: int | None = None
    client_ip: str = ''
    user_agent: str = ''


@dataclass(frozen=True)
class InteractiveSessionStarted:
    session_id: str
    status: str
    command_kind: str
    service_id: int | None
    expires_at: datetime


class StartInteractiveSessionUseCase:
    """Validate and persist a new PENDING interactive session for an app."""

    def execute(self, cmd: StartInteractiveSessionCommand) -> InteractiveSessionStarted:
        app = App.objects.get(id=cmd.app_id, deleted_at__isnull=True)
        get_interactive_driver(cmd.command_kind)

        service = None
        manage_path = 'manage.py'
        if cmd.command_kind == InteractiveRunCommandKind.POSTGRES_CONNECT:
            service = self._resolve_postgres_connect_service(app, cmd.service_id)
        else:
            if not app.name_dokku:
                raise DeploymentFailed(reason='App sem name_dokku configurado', step='validate')
            manage_path = validate_manage_path(cmd.manage_path)

        cleanup_expired_interactive_sessions()
        if not has_live_interactive_runner():
            raise InteractiveRunnerUnavailable()

        session = InteractiveRunSession.objects.create(
            app=app,
            service=service,
            created_by_id=cmd.user_id,
            command_kind=cmd.command_kind,
            status=InteractiveRunSessionStatus.PENDING,
            manage_path=manage_path,
            client_ip=cmd.client_ip,
            user_agent=cmd.user_agent[:1000],
            expires_at=get_interactive_session_expires_at(),
            last_activity_at=timezone.now(),
        )

        return InteractiveSessionStarted(
            session_id=str(session.id),
            status=session.status,
            command_kind=session.command_kind,
            service_id=session.service_id,
            expires_at=session.expires_at,
        )

    def _resolve_postgres_connect_service(self, app: App, service_id: int | None) -> Service:
        queryset = Service.objects.filter(
            app=app, project=app.project, service_type__in=postgres_service_types(), deleted_at__isnull=True
        )

        if service_id is not None:
            service = queryset.filter(id=service_id).first()
            if not service:
                raise ApplicationDomainError('Servico Postgres nao encontrado para este app.')
        else:
            services = list(queryset.order_by('name', 'id')[:2])
            if not services:
                raise ApplicationDomainError('Este app nao tem um servico Postgres vinculado.')
            if len(services) > 1:
                raise ApplicationDomainError('Este app tem mais de um Postgres. Informe --service para escolher.')
            service = services[0]

        if not service.container_name:
            raise ApplicationDomainError('Servico Postgres ainda nao foi provisionado no Dokku.')

        return service
