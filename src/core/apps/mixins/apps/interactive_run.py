import base64
import hashlib
import re
import shlex
import socket
import time
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import cast

import paramiko
from celery import Task, shared_task
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.adapters import DokkuAdapter
from core.apps.models import (
    App,
    InteractiveRunCommandKind,
    InteractiveRunEvent,
    InteractiveRunEventType,
    InteractiveRunSession,
    InteractiveRunSessionStatus,
)
from core.logs.models import AppLogManager, LogCategory

INTERACTIVE_RUN_POLL_INTERVAL = 0.2
INTERACTIVE_RUN_OUTPUT_CHUNK_SIZE = 4096
INTERACTIVE_SUCCESS_MARKERS = (
    'superuser created successfully',
    'superusuario criado com sucesso',
    'superusuário criado com sucesso',
)
SENSITIVE_OUTPUT_REDACTION = '[conteudo sensivel ocultado]'
TERMINAL_SESSION_STATUSES = {
    InteractiveRunSessionStatus.COMPLETED,
    InteractiveRunSessionStatus.FAILED,
    InteractiveRunSessionStatus.CANCELLED,
    InteractiveRunSessionStatus.EXPIRED,
}


class InteractiveRunCancelled(RuntimeError):
    """Encerramento explicito solicitado pelo usuario."""


class InteractiveRunExpired(RuntimeError):
    """Sessao expirada por inatividade."""


@dataclass(frozen=True)
class InteractivePromptSpec:
    key: str
    label: str
    secret: bool
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class InteractivePromptMatch:
    spec: InteractivePromptSpec
    text: str
    start: int
    end: int


class DjangoCreatesuperuserDriver:
    command_kind = InteractiveRunCommandKind.DJANGO_CREATESUPERUSER
    display_name = 'Django createsuperuser'
    log_category = LogCategory.DATABASE
    prompt_specs = (
        InteractivePromptSpec(
            key='email',
            label='Email',
            secret=False,
            pattern=re.compile(r'((?:e-?mail(?:\s+address)?|email(?:\s+address)?)\s*:\s*)$', re.IGNORECASE),
        ),
        InteractivePromptSpec(
            key='name',
            label='Name',
            secret=False,
            pattern=re.compile(r'((?:name|nome)\s*:\s*)$', re.IGNORECASE),
        ),
        InteractivePromptSpec(
            key='password_validation_bypass',
            label='Bypass password validation',
            secret=False,
            pattern=re.compile(
                r'((?=[^\n]*(?:bypass|ignorar|desconsiderar))'
                r'(?=[^\n]*(?:password|senha))'
                r'(?=[^\n]*(?:validation|valida(?:ç|c)[aã]o))'
                r'(?=[^\n]*\[(?:y|s)/N\])[^\n]*:\s*)$',
                re.IGNORECASE,
            ),
        ),
        InteractivePromptSpec(
            key='password_confirmation',
            label='Password (again)',
            secret=True,
            pattern=re.compile(r'((?:password|senha)\s*\((?:again|novamente)\)\s*:\s*)$', re.IGNORECASE),
        ),
        InteractivePromptSpec(
            key='password',
            label='Password',
            secret=True,
            pattern=re.compile(r'((?:password|senha)\s*:\s*)$', re.IGNORECASE),
        ),
    )

    def build_command(self, manage_path: str) -> str:
        parts = ['python', manage_path, 'createsuperuser']
        return ' '.join(shlex.quote(part) for part in parts)

    def match_prompt(self, buffer: str) -> InteractivePromptMatch | None:
        for prompt_spec in self.prompt_specs:
            match = prompt_spec.pattern.search(buffer)
            if match:
                return InteractivePromptMatch(
                    spec=prompt_spec,
                    text=match.group(1),
                    start=match.start(1),
                    end=match.end(1),
                )
        return None


INTERACTIVE_COMMAND_DRIVERS = {
    InteractiveRunCommandKind.DJANGO_CREATESUPERUSER: DjangoCreatesuperuserDriver(),
}


def get_interactive_driver(command_kind: str):
    driver = INTERACTIVE_COMMAND_DRIVERS.get(command_kind)
    if driver is None:
        raise ValueError(f'Comando interativo nao suportado: {command_kind}')
    return driver


def get_interactive_session_idle_timeout() -> timedelta:
    seconds = int(getattr(settings, 'CLI_INTERACTIVE_SESSION_IDLE_SECONDS', 300))
    return timedelta(seconds=seconds)


def get_interactive_session_expires_at(now=None):
    now = now or timezone.now()
    return now + get_interactive_session_idle_timeout()


def cleanup_expired_interactive_sessions():
    now = timezone.now()
    InteractiveRunSession.objects.filter(
        expires_at__lt=now,
    ).exclude(
        status__in=TERMINAL_SESSION_STATUSES,
    ).update(
        status=InteractiveRunSessionStatus.EXPIRED,
        completed_at=now,
        cancel_requested=True,
        awaiting_prompt_id=None,
        awaiting_prompt_text=None,
        awaiting_prompt_secret=False,
        pending_answer_prompt_id=None,
        pending_answer_ciphertext=None,
        pending_answer_received_at=None,
    )


@lru_cache(maxsize=1)
def _interactive_answer_fernet() -> Fernet:
    key_material = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    key = base64.urlsafe_b64encode(key_material)
    return Fernet(key)


def encrypt_interactive_answer(value: str) -> bytes:
    return _interactive_answer_fernet().encrypt(value.encode('utf-8'))


def decrypt_interactive_answer(value: bytes | memoryview) -> str:
    raw_value = bytes(value)
    return _interactive_answer_fernet().decrypt(raw_value).decode('utf-8')


def _touch_locked_session(session: InteractiveRunSession, *, now=None):
    now = now or timezone.now()
    session.last_activity_at = now
    session.expires_at = get_interactive_session_expires_at(now)


def _create_session_event(
    session: InteractiveRunSession,
    event_type: str,
    payload: dict,
    *,
    touch: bool = True,
):
    event = InteractiveRunEvent.objects.create(session=session, event_type=event_type, payload=payload)
    if touch and session.status not in TERMINAL_SESSION_STATUSES:
        _touch_locked_session(session)
        session.save(update_fields=['last_activity_at', 'expires_at'])
    return event


def submit_interactive_session_answer(session_id: str, prompt_id: str, value: str):
    with transaction.atomic():
        session = InteractiveRunSession.objects.select_for_update().get(id=session_id)
        if session.status != InteractiveRunSessionStatus.AWAITING_INPUT:
            raise ValueError('A sessao nao esta aguardando entrada neste momento.')
        if session.awaiting_prompt_id != prompt_id:
            raise ValueError('Prompt invalido ou ja substituido por outro.')
        if session.pending_answer_ciphertext:
            raise ValueError('Ja existe uma resposta pendente para este prompt.')

        now = timezone.now()
        session.pending_answer_prompt_id = prompt_id
        session.pending_answer_ciphertext = encrypt_interactive_answer(value)
        session.pending_answer_received_at = now
        _touch_locked_session(session, now=now)
        session.save(
            update_fields=[
                'pending_answer_prompt_id',
                'pending_answer_ciphertext',
                'pending_answer_received_at',
                'last_activity_at',
                'expires_at',
            ]
        )
        return session


def request_interactive_session_cancel(session_id: str):
    with transaction.atomic():
        session = InteractiveRunSession.objects.select_for_update().get(id=session_id)
        if session.status in TERMINAL_SESSION_STATUSES:
            return session

        session.cancel_requested = True
        _touch_locked_session(session)
        session.save(update_fields=['cancel_requested', 'last_activity_at', 'expires_at'])
        _create_session_event(
            session,
            InteractiveRunEventType.STATUS,
            {'message': 'Cancelamento solicitado pela CLI.', 'status': 'cancelling'},
        )
        return session


def _consume_interactive_session_answer(session_id: str) -> str | None:
    with transaction.atomic():
        session = InteractiveRunSession.objects.select_for_update().get(id=session_id)
        if not session.pending_answer_ciphertext or not session.awaiting_prompt_id:
            return None

        answer = decrypt_interactive_answer(session.pending_answer_ciphertext)
        now = timezone.now()
        session.status = InteractiveRunSessionStatus.RUNNING
        session.awaiting_prompt_id = None
        session.awaiting_prompt_text = None
        session.awaiting_prompt_secret = False
        session.pending_answer_prompt_id = None
        session.pending_answer_ciphertext = None
        session.pending_answer_received_at = None
        _touch_locked_session(session, now=now)
        session.save(
            update_fields=[
                'status',
                'awaiting_prompt_id',
                'awaiting_prompt_text',
                'awaiting_prompt_secret',
                'pending_answer_prompt_id',
                'pending_answer_ciphertext',
                'pending_answer_received_at',
                'last_activity_at',
                'expires_at',
            ]
        )
        return answer


def _set_session_prompt(session_id: str, prompt_match: InteractivePromptMatch):
    with transaction.atomic():
        session = InteractiveRunSession.objects.select_for_update().get(id=session_id)
        session.prompt_counter += 1
        prompt_id = f'{prompt_match.spec.key}-{session.prompt_counter}'
        session.status = InteractiveRunSessionStatus.AWAITING_INPUT
        session.awaiting_prompt_id = prompt_id
        session.awaiting_prompt_text = prompt_match.text.strip()
        session.awaiting_prompt_secret = prompt_match.spec.secret
        _touch_locked_session(session)
        session.save(
            update_fields=[
                'prompt_counter',
                'status',
                'awaiting_prompt_id',
                'awaiting_prompt_text',
                'awaiting_prompt_secret',
                'last_activity_at',
                'expires_at',
            ]
        )
        _create_session_event(
            session,
            InteractiveRunEventType.PROMPT,
            {
                'prompt_id': prompt_id,
                'text': prompt_match.text,
                'label': prompt_match.spec.label,
                'secret': prompt_match.spec.secret,
            },
            touch=False,
        )
        return prompt_id


def _mark_session_terminal(session_id: str, status: str, event_type: str, payload: dict):
    with transaction.atomic():
        session = InteractiveRunSession.objects.select_for_update().get(id=session_id)
        now = timezone.now()
        session.status = status
        session.completed_at = now
        session.awaiting_prompt_id = None
        session.awaiting_prompt_text = None
        session.awaiting_prompt_secret = False
        session.pending_answer_prompt_id = None
        session.pending_answer_ciphertext = None
        session.pending_answer_received_at = None
        session.save(
            update_fields=[
                'status',
                'completed_at',
                'awaiting_prompt_id',
                'awaiting_prompt_text',
                'awaiting_prompt_secret',
                'pending_answer_prompt_id',
                'pending_answer_ciphertext',
                'pending_answer_received_at',
            ]
        )
        _create_session_event(session, event_type, payload, touch=False)
        return session


def _get_session_control_state(session_id: str) -> InteractiveRunSession:
    return InteractiveRunSession.objects.only(
        'id',
        'status',
        'expires_at',
        'cancel_requested',
        'awaiting_prompt_id',
        'awaiting_prompt_secret',
    ).get(id=session_id)


def _normalize_terminal_output(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _emit_output_lines(
    session: InteractiveRunSession,
    text: str,
    logger: AppLogManager,
    *,
    category: str,
    suppressed_echoes: set[str] | None = None,
    sensitive_values: set[str] | None = None,
    output_state: dict | None = None,
):
    suppressed_echoes = suppressed_echoes or set()
    sensitive_values = sensitive_values or set()

    for line in text.split('\n'):
        normalized_line = line.strip()
        if not normalized_line:
            continue

        if normalized_line in suppressed_echoes:
            continue

        safe_line = normalized_line
        if any(secret and secret in normalized_line for secret in sensitive_values):
            safe_line = SENSITIVE_OUTPUT_REDACTION

        if output_state is not None and any(marker in safe_line.lower() for marker in INTERACTIVE_SUCCESS_MARKERS):
            output_state['saw_success_output'] = True

        _create_session_event(
            session,
            InteractiveRunEventType.OUTPUT,
            {'message': safe_line},
        )
        logger.dokku(safe_line, category=category)


def _flush_output_buffer(
    session: InteractiveRunSession,
    buffer: str,
    driver,
    logger: AppLogManager,
    *,
    suppressed_echoes: set[str],
    sensitive_values: set[str],
    output_state: dict,
) -> str:
    prompt_match = driver.match_prompt(buffer)
    if prompt_match is not None:
        output_before_prompt = buffer[:prompt_match.start]
        if output_before_prompt:
            _emit_output_lines(
                session,
                output_before_prompt,
                logger,
                category=driver.log_category,
                suppressed_echoes=suppressed_echoes,
                sensitive_values=sensitive_values,
                output_state=output_state,
            )
        _set_session_prompt(str(session.id), prompt_match)
        return buffer[prompt_match.end :]

    if '\n' not in buffer:
        return buffer

    lines = buffer.split('\n')
    trailing_fragment = lines.pop()
    _emit_output_lines(
        session,
        '\n'.join(lines),
        logger,
        category=driver.log_category,
        suppressed_echoes=suppressed_echoes,
        sensitive_values=sensitive_values,
        output_state=output_state,
    )
    return trailing_fragment


def _read_channel_output(channel) -> str:
    parts = []

    while channel.recv_ready():
        parts.append(channel.recv(INTERACTIVE_RUN_OUTPUT_CHUNK_SIZE).decode('utf-8', errors='replace'))

    while channel.recv_stderr_ready():
        parts.append(channel.recv_stderr(INTERACTIVE_RUN_OUTPUT_CHUNK_SIZE).decode('utf-8', errors='replace'))

    return ''.join(parts)


def _open_interactive_command(dokku_adapter: DokkuAdapter, full_command: str):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = dokku_adapter._get_pkey()
    client.connect(
        dokku_adapter.host,
        port=dokku_adapter.port,
        username=dokku_adapter.username,
        pkey=pkey,
    )
    stdin, stdout, stderr = client.exec_command(full_command, get_pty=True)
    stdout.channel.settimeout(INTERACTIVE_RUN_POLL_INTERVAL)
    stderr.channel.settimeout(INTERACTIVE_RUN_POLL_INTERVAL)
    return client, stdin, stdout, stderr


def _run_interactive_command_loop(
    session: InteractiveRunSession,
    driver,
    dokku_adapter: DokkuAdapter,
    logger: AppLogManager,
):
    command = driver.build_command(session.manage_path)
    full_command = f'run {session.app.name_dokku} {command}'
    client, stdin, stdout, _stderr = _open_interactive_command(dokku_adapter, full_command)
    buffer = ''
    output_state = {'saw_success_output': False}
    sensitive_values: set[str] = set()
    suppressed_echoes: set[str] = set()

    try:
        while True:
            control_state = _get_session_control_state(str(session.id))
            if control_state.cancel_requested:
                raise InteractiveRunCancelled('Sessao cancelada pelo usuario.')
            if control_state.expires_at <= timezone.now():
                raise InteractiveRunExpired('Sessao expirada por inatividade.')

            try:
                output = _read_channel_output(stdout.channel)
            except socket.timeout:
                output = ''

            if output:
                buffer = _normalize_terminal_output(buffer + output)
                buffer = _flush_output_buffer(
                    session,
                    buffer,
                    driver,
                    logger,
                    suppressed_echoes=suppressed_echoes,
                    sensitive_values=sensitive_values,
                    output_state=output_state,
                )

            if control_state.status == InteractiveRunSessionStatus.AWAITING_INPUT:
                answer = _consume_interactive_session_answer(str(session.id))
                if answer is not None:
                    stripped_answer = answer.strip()
                    if stripped_answer:
                        suppressed_echoes.add(stripped_answer)
                        if control_state.awaiting_prompt_secret:
                            sensitive_values.add(stripped_answer)
                    stdin.write(answer + '\n')
                    stdin.flush()

            if stdout.channel.exit_status_ready():
                trailing_output = _read_channel_output(stdout.channel)
                if trailing_output:
                    buffer = _normalize_terminal_output(buffer + trailing_output)
                    buffer = _flush_output_buffer(
                        session,
                        buffer,
                        driver,
                        logger,
                        suppressed_echoes=suppressed_echoes,
                        sensitive_values=sensitive_values,
                        output_state=output_state,
                    )

                if buffer.strip():
                    _emit_output_lines(
                        session,
                        buffer,
                        logger,
                        category=driver.log_category,
                        suppressed_echoes=suppressed_echoes,
                        sensitive_values=sensitive_values,
                        output_state=output_state,
                    )
                    buffer = ''
                break

            time.sleep(INTERACTIVE_RUN_POLL_INTERVAL)

        return stdout.channel.recv_exit_status(), output_state
    finally:
        try:
            stdin.close()
        except Exception:
            pass
        client.close()


class InteractiveRunMixin:
    """Infraestrutura generica para sessoes interativas executadas via Dokku."""

    @shared_task(bind=True)
    def run_interactive_session(self, session_id: str) -> dict:
        task = cast(Task, self)
        task_id = task.request.id

        try:
            session = InteractiveRunSession.objects.select_related('app').get(id=session_id)
        except InteractiveRunSession.DoesNotExist as e:
            raise RuntimeError('Sessao interativa nao encontrada.') from e

        app = session.app
        if not app.name_dokku:
            raise RuntimeError('App sem name_dokku configurado.')

        driver = get_interactive_driver(session.command_kind)
        dokku_adapter = DokkuAdapter()
        logger = AppLogManager(app, task_id)
        cleanup_expired_interactive_sessions()

        session.task_id = task_id
        session.status = InteractiveRunSessionStatus.RUNNING
        session.started_at = timezone.now()
        _touch_locked_session(session, now=session.started_at)
        session.save(update_fields=['task_id', 'status', 'started_at', 'last_activity_at', 'expires_at'])

        _create_session_event(
            session,
            InteractiveRunEventType.STATUS,
            {
                'status': InteractiveRunSessionStatus.RUNNING,
                'message': f'Iniciando {driver.display_name}.',
            },
            touch=False,
        )
        logger.info(
            f'Iniciando sessao interativa: {driver.display_name}',
            category=driver.log_category,
            metadata={'command_kind': session.command_kind, 'manage_path': session.manage_path},
        )

        try:
            exit_status, output_state = _run_interactive_command_loop(session, driver, dokku_adapter, logger)
            if exit_status != 0:
                raise RuntimeError(f'Comando interativo finalizado com codigo {exit_status}.')

            _mark_session_terminal(
                str(session.id),
                InteractiveRunSessionStatus.COMPLETED,
                InteractiveRunEventType.COMPLETE,
                {
                    'message': 'Superusuario criado com sucesso.',
                    'silent': bool(output_state.get('saw_success_output')),
                },
            )
            logger.success(
                'Sessao interativa concluida com sucesso.',
                category=driver.log_category,
                metadata={'command_kind': session.command_kind},
            )
            return {
                'status': 'success',
                'message': 'Sessao interativa concluida com sucesso.',
                'session_id': str(session.id),
                'app_id': app.id,
            }
        except InteractiveRunCancelled as e:
            _mark_session_terminal(
                str(session.id),
                InteractiveRunSessionStatus.CANCELLED,
                InteractiveRunEventType.ERROR,
                {'message': str(e)},
            )
            logger.warning(str(e), category=driver.log_category, metadata={'command_kind': session.command_kind})
            raise
        except InteractiveRunExpired as e:
            _mark_session_terminal(
                str(session.id),
                InteractiveRunSessionStatus.EXPIRED,
                InteractiveRunEventType.ERROR,
                {'message': str(e)},
            )
            logger.warning(str(e), category=driver.log_category, metadata={'command_kind': session.command_kind})
            raise
        except Exception as e:
            _mark_session_terminal(
                str(session.id),
                InteractiveRunSessionStatus.FAILED,
                InteractiveRunEventType.ERROR,
                {'message': str(e)},
            )
            logger.error(
                f'Erro na sessao interativa: {e}',
                category=driver.log_category,
                metadata={'command_kind': session.command_kind, 'error_type': type(e).__name__},
            )
            raise
