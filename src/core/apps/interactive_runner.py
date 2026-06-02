import os
import socket
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from core.apps.mixins.apps.interactive_run import cleanup_expired_interactive_sessions
from core.apps.models import InteractiveRunRunner, InteractiveRunSession, InteractiveRunSessionStatus


def get_interactive_runner_heartbeat_seconds() -> int:
    return max(1, int(getattr(settings, 'CLI_INTERACTIVE_RUNNER_HEARTBEAT_SECONDS', 10)))


def get_interactive_runner_stale_before(now=None):
    now = now or timezone.now()
    return now - timedelta(seconds=get_interactive_runner_heartbeat_seconds() * 3)


def get_interactive_max_sessions() -> int:
    return max(1, int(getattr(settings, 'CLI_INTERACTIVE_MAX_SESSIONS', 20)))


def build_default_runner_id() -> str:
    return f'{socket.gethostname()}:{os.getpid()}'


def touch_interactive_runner(
    runner_id: str,
    *,
    active_sessions: int = 0,
    max_sessions: int | None = None,
    metadata: dict | None = None,
) -> InteractiveRunRunner:
    now = timezone.now()
    runner, _created = InteractiveRunRunner.objects.update_or_create(
        runner_id=runner_id,
        defaults={
            'hostname': socket.gethostname(),
            'pid': os.getpid(),
            'active_sessions': max(0, active_sessions),
            'max_sessions': max_sessions or get_interactive_max_sessions(),
            'last_heartbeat_at': now,
            'metadata': metadata or {},
        },
    )
    return runner


def get_live_interactive_runner_ids(now=None) -> list[str]:
    cutoff = get_interactive_runner_stale_before(now)
    return list(
        InteractiveRunRunner.objects.filter(last_heartbeat_at__gte=cutoff).values_list('runner_id', flat=True)
    )


def has_live_interactive_runner(now=None) -> bool:
    cutoff = get_interactive_runner_stale_before(now)
    return InteractiveRunRunner.objects.filter(last_heartbeat_at__gte=cutoff).exists()


def release_stale_interactive_claims(now=None):
    live_runner_ids = get_live_interactive_runner_ids(now)
    claimed_pending = InteractiveRunSession.objects.filter(
        status=InteractiveRunSessionStatus.PENDING,
        runner_id__isnull=False,
    )
    if live_runner_ids:
        claimed_pending = claimed_pending.exclude(runner_id__in=live_runner_ids)
    return claimed_pending.update(runner_id=None, claimed_at=None)


def claim_pending_interactive_sessions(runner_id: str, *, limit: int) -> list[InteractiveRunSession]:
    if limit <= 0:
        return []

    now = timezone.now()
    cleanup_expired_interactive_sessions()
    release_stale_interactive_claims(now)

    with transaction.atomic():
        select_for_update_kwargs = {}
        if connection.features.has_select_for_update_skip_locked:
            select_for_update_kwargs['skip_locked'] = True

        queryset = (
            InteractiveRunSession.objects.select_for_update(**select_for_update_kwargs)
            .select_related('app', 'service')
            .filter(
                status=InteractiveRunSessionStatus.PENDING,
                runner_id__isnull=True,
                expires_at__gt=now,
            )
            .order_by('created_at')[:limit]
        )
        sessions = list(queryset)

        for session in sessions:
            session.runner_id = runner_id
            session.claimed_at = now
            session.save(update_fields=['runner_id', 'claimed_at', 'updated_at'])

    return sessions
