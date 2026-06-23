import hashlib
import inspect
import logging
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

SENSITIVE_KEY_PATTERN = re.compile(
    r'(?i)(API_KEY|BROKER_URL|DATABASE_URL|DSN|KEY|PASS|PASSWORD|PWD|RABBITMQ_URL|REDIS_URL|SECRET|TOKEN)'
)
URL_CREDENTIALS_PATTERN = re.compile(r'([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@', re.IGNORECASE)
ASSIGNMENT_PATTERN = re.compile(r'(\b[A-Za-z_][A-Za-z0-9_]*=)([^\s]+)')
PASSWORD_FLAG_PATTERN = re.compile(r'((?:--password|-p)\s+)([^\s]+)', re.IGNORECASE)

_ssh_audit_context: ContextVar[dict[str, Any]] = ContextVar('ssh_audit_context', default={})


@dataclass
class SSHAuditResult:
    started_at: float
    sanitized_command: str
    command_hash: str
    command_family: str
    context: dict[str, Any] = field(default_factory=dict)


def sanitize_ssh_command(command: str) -> str:
    redacted = URL_CREDENTIALS_PATTERN.sub(r'\1[credentials]@', command)
    redacted = PASSWORD_FLAG_PATTERN.sub(r'\1[oculto]', redacted)

    def replace_assignment(match: re.Match) -> str:
        key = match.group(1)[:-1]
        if SENSITIVE_KEY_PATTERN.search(key):
            return f'{match.group(1)}[oculto]'
        return match.group(0)

    return ASSIGNMENT_PATTERN.sub(replace_assignment, redacted)


def get_command_family(command: str) -> str:
    first = (command or '').strip().split(maxsplit=1)[0] if command else ''
    if first in {'run', 'logs'}:
        return first
    return first.split(':', 1)[0] if first else 'ssh'


def _hash_command(command: str) -> str:
    return hashlib.sha256(command.encode('utf-8')).hexdigest()


def _find_caller() -> dict[str, str]:
    for frame_info in inspect.stack()[2:12]:
        filename = frame_info.filename.replace('\\', '/')
        if '/core/adapters/' in filename or '/core/logs/ssh_audit.py' in filename:
            continue
        module = inspect.getmodule(frame_info.frame)
        module_name = module.__name__ if module else ''
        return {
            'caller_module': module_name,
            'caller_function': frame_info.function,
        }
    return {}


def _current_celery_context() -> dict[str, Any]:
    try:
        from celery import current_task  # noqa: PLC0415

        task = current_task
        request = getattr(task, 'request', None)
        task_id = getattr(request, 'id', None)
        task_name = getattr(task, 'name', None)
        if task_id or task_name:
            return {
                'task_id': task_id,
                'metadata': {
                    'celery_task_name': task_name,
                },
            }
    except Exception:
        return {}
    return {}


def get_ssh_audit_context(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    context = dict(_ssh_audit_context.get() or {})
    celery_context = _current_celery_context()
    if celery_context:
        context.setdefault('task_id', celery_context.get('task_id'))
        metadata = dict(context.get('metadata') or {})
        metadata.update(celery_context.get('metadata') or {})
        context['metadata'] = metadata
    if extra:
        metadata = dict(context.get('metadata') or {})
        extra_metadata = dict(extra.get('metadata') or {})
        context.update({key: value for key, value in extra.items() if key != 'metadata' and value is not None})
        metadata.update(extra_metadata)
        if metadata:
            context['metadata'] = metadata
    caller = _find_caller()
    metadata = dict(context.get('metadata') or {})
    metadata.update({key: value for key, value in caller.items() if value})
    if metadata:
        context['metadata'] = metadata
    context.setdefault('origin', caller.get('caller_module') or 'unknown')
    return context


@contextmanager
def ssh_audit_context(**kwargs):
    current = dict(_ssh_audit_context.get() or {})
    metadata = dict(current.get('metadata') or {})
    metadata.update(kwargs.pop('metadata', {}) or {})
    current.update({key: value for key, value in kwargs.items() if value is not None})
    if metadata:
        current['metadata'] = metadata
    token = _ssh_audit_context.set(current)
    try:
        yield
    finally:
        _ssh_audit_context.reset(token)


def begin_ssh_audit(command: str, context: dict[str, Any] | None = None) -> SSHAuditResult:
    sanitized_command = sanitize_ssh_command(command)
    return SSHAuditResult(
        started_at=time.monotonic(),
        sanitized_command=sanitized_command,
        command_hash=_hash_command(sanitized_command),
        command_family=get_command_family(command),
        context=get_ssh_audit_context(context),
    )


def finish_ssh_audit(
    audit: SSHAuditResult,
    *,
    status: str,
    exit_status: int | None = None,
    error_summary: str = '',
) -> None:
    if not getattr(settings, 'SSH_AUDIT_ENABLED', True):
        return

    duration_ms = max(0, int((time.monotonic() - audit.started_at) * 1000))
    context = audit.context
    metadata = dict(context.get('metadata') or {})

    payload = {
        'origin': context.get('origin') or '',
        'command_family': audit.command_family,
        'sanitized_command': audit.sanitized_command,
        'command_hash': audit.command_hash,
        'status': status,
        'exit_status': exit_status,
        'duration_ms': duration_ms,
        'task_id': context.get('task_id'),
        'request_path': context.get('request_path') or '',
        'request_method': context.get('request_method') or '',
        'error_summary': (error_summary or '')[:2000],
        'metadata': metadata,
    }

    logger.info('ssh_command_audit', extra={'ssh_audit': payload})

    try:
        from core.logs.models import SSHCommandAudit  # noqa: PLC0415

        SSHCommandAudit.objects.create(
            user_id=context.get('user_id'),
            app_id=context.get('app_id'),
            service_id=context.get('service_id'),
            **payload,
        )
    except Exception:
        logger.exception('Falha ao registrar auditoria SSH.')
