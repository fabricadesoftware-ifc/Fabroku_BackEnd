import logging

from observability.models import AdminNotification, LogLevel

logger = logging.getLogger(__name__)


def notify_admins(  # noqa: PLR0913
    event_type: str,
    title: str,
    message: str = '',
    *,
    app=None,
    service=None,
    level: str = LogLevel.ERROR,
    metadata: dict | None = None,
) -> AdminNotification | None:
    """Best-effort: falhar ao notificar nunca pode quebrar o fluxo que detectou o erro."""
    try:
        return AdminNotification.objects.create(
            event_type=event_type,
            level=level,
            title=title[:255],
            message=message[:5000],
            app=app,
            service=service,
            metadata=metadata or {},
        )
    except Exception:
        logger.exception('Falha ao criar AdminNotification (%s: %s)', event_type, title)
        return None
