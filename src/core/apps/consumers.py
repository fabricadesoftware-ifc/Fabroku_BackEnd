import asyncio
import json
from contextlib import suppress
from json import JSONDecodeError
from urllib.parse import parse_qs

from channels.db import database_sync_to_async

from core.apps.interactive_crypto import decrypt_interactive_text
from core.apps.mixins.apps.interactive_run import (
    queue_interactive_terminal_input,
    request_interactive_session_cancel,
    submit_interactive_session_answer,
)
from core.apps.models import (
    InteractiveRunAuditChunk,
    InteractiveRunAuditDirection,
    InteractiveRunCommandKind,
    InteractiveRunEvent,
    InteractiveRunSession,
)

DATABASE_STREAM_POLL_SECONDS = 0.2
TERMINAL_MESSAGE_TYPES = {'complete', 'error'}


def _event_message(event: InteractiveRunEvent) -> dict:
    return {
        'type': event.event_type,
        'id': event.id,
        **event.payload,
    }


def _terminal_output_message(chunk: InteractiveRunAuditChunk) -> dict:
    return {
        'type': 'terminal.output',
        'output_id': chunk.id,
        'sequence': chunk.sequence,
        'content': decrypt_interactive_text(chunk.content_ciphertext),
    }


@database_sync_to_async
def _get_session_snapshot(app_id: int, session_id: str, user_id: int):
    session = (
        InteractiveRunSession.objects.select_related('app', 'service', 'created_by')
        .filter(id=session_id, app_id=app_id, created_by_id=user_id)
        .first()
    )
    if not session:
        return None

    return {
        'id': str(session.id),
        'command_kind': session.command_kind,
        'status': session.status,
    }


@database_sync_to_async
def _load_replay_messages(session_id: str, command_kind: str, after_event: int, after_output: int):
    messages = []

    if command_kind == InteractiveRunCommandKind.POSTGRES_CONNECT:
        output_chunks = (
            InteractiveRunAuditChunk.objects.filter(
                session_id=session_id,
                direction=InteractiveRunAuditDirection.OUTPUT,
                id__gt=after_output,
            )
            .order_by('id')[:100]
        )
        messages.extend(_terminal_output_message(chunk) for chunk in output_chunks)

    events = InteractiveRunEvent.objects.filter(session_id=session_id, id__gt=after_event).order_by('id')[:100]
    messages.extend(_event_message(event) for event in events)
    return messages


@database_sync_to_async
def _submit_answer(session_id: str, prompt_id: str, value: str):
    submit_interactive_session_answer(session_id, prompt_id, value)


@database_sync_to_async
def _queue_input(session_id: str, value: str):
    return queue_interactive_terminal_input(session_id, value)


@database_sync_to_async
def _cancel_session(session_id: str):
    request_interactive_session_cancel(session_id)


class InteractiveSessionConsumer:
    """WebSocket ASGI puro para sessoes interativas da CLI.

    Evitamos herdar dos consumers do Channels aqui de proposito. Eles sempre
    escutam o channel layer interno, o que fazia sessoes longas cairem quando o
    Redis demorava a responder, mesmo sem usarmos groups.
    """

    @classmethod
    def as_asgi(cls):
        async def application(scope, receive, send):
            consumer = cls(scope)
            await consumer(receive, send)

        return application

    def __init__(self, scope):
        self.scope = scope
        self.asgi_receive = None
        self.asgi_send = None
        self.app_id = None
        self.session_id = None
        self.session = None
        self.last_event_id = 0
        self.last_output_id = 0
        self.connected = False
        self.stream_task = None
        self.send_lock = asyncio.Lock()

    async def __call__(self, receive, send):
        self.asgi_receive = receive
        self.asgi_send = send

        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self._close(4401)
            return

        self.app_id = int(self.scope['url_route']['kwargs']['app_id'])
        self.session_id = str(self.scope['url_route']['kwargs']['session_id'])
        query = parse_qs(self.scope.get('query_string', b'').decode('utf-8', errors='ignore'))
        self.last_event_id = self._query_int(query, 'after_event')
        self.last_output_id = self._query_int(query, 'after_output')

        self.session = await _get_session_snapshot(self.app_id, self.session_id, user.id)
        if not self.session:
            await self._close(4404)
            return

        await self._accept()
        await self._send_json({
            'type': 'status',
            'status': self.session['status'],
            'message': 'Conectado a sessao interativa.',
        })
        self.stream_task = asyncio.create_task(self._stream_database_messages())

        try:
            while self.connected:
                message = await receive()
                message_type = message.get('type')

                if message_type == 'websocket.disconnect':
                    return

                if message_type != 'websocket.receive':
                    continue

                content = self._decode_websocket_message(message)
                if content is None:
                    await self._send_json({'type': 'error', 'message': 'Mensagem WebSocket invalida.'})
                    continue

                await self._receive_json(content)
        finally:
            self.connected = False
            await self._cancel_stream_task()

    async def _cancel_stream_task(self):
        stream_task = getattr(self, 'stream_task', None)
        if stream_task and not stream_task.done():
            stream_task.cancel()
            with suppress(asyncio.CancelledError):
                await stream_task

    async def _receive_json(self, content):
        message_type = content.get('type')

        try:
            if message_type == 'answer':
                await _submit_answer(
                    self.session_id,
                    str(content.get('prompt_id') or ''),
                    str(content.get('value') if content.get('value') is not None else ''),
                )
                await self._send_json({'type': 'ack', 'action': 'answer'})
                return

            if message_type == 'input':
                input_data = str(content.get('data') if content.get('data') is not None else '')
                if input_data:
                    chunk = await _queue_input(self.session_id, input_data)
                    await self._send_json({'type': 'ack', 'action': 'input', 'chunk_id': chunk.id})
                return

            if message_type == 'cancel':
                await _cancel_session(self.session_id)
                await self._send_json({'type': 'ack', 'action': 'cancel'})
                return

            if message_type == 'ping':
                await self._send_json({'type': 'pong'})
                return

            await self._send_json({'type': 'error', 'message': 'Mensagem WebSocket nao suportada.'})
        except ValueError as exc:
            await self._send_json({'type': 'error', 'message': str(exc)})

    async def _stream_database_messages(self):
        while self.connected:
            messages = await _load_replay_messages(
                self.session_id,
                self.session['command_kind'],
                self.last_event_id,
                self.last_output_id,
            )

            should_stop = False
            for message in messages:
                self._track_message_offsets(message)
                await self._send_json(message)
                if message.get('type') in TERMINAL_MESSAGE_TYPES:
                    should_stop = True

            if should_stop:
                return

            await asyncio.sleep(DATABASE_STREAM_POLL_SECONDS)

    async def _send_json(self, content: dict):
        if not self.connected:
            return

        async with self.send_lock:
            if not self.connected:
                return
            await self.asgi_send({
                'type': 'websocket.send',
                'text': json.dumps(content),
            })

    async def _accept(self):
        self.connected = True
        await self.asgi_send({'type': 'websocket.accept'})

    async def _close(self, code: int):
        await self.asgi_send({'type': 'websocket.close', 'code': code})

    @staticmethod
    def _decode_websocket_message(message: dict):
        raw_content = message.get('text')
        if raw_content is None and message.get('bytes') is not None:
            raw_content = message['bytes'].decode('utf-8', errors='ignore')
        if raw_content is None:
            return {}

        try:
            parsed = json.loads(raw_content)
        except (JSONDecodeError, TypeError):
            return None

        return parsed if isinstance(parsed, dict) else None

    def _track_message_offsets(self, message: dict):
        if message.get('output_id'):
            self.last_output_id = max(self.last_output_id, int(message['output_id']))
        if message.get('id'):
            self.last_event_id = max(self.last_event_id, int(message['id']))

    @staticmethod
    def _query_int(query: dict, key: str) -> int:
        try:
            return int((query.get(key) or ['0'])[0] or 0)
        except (TypeError, ValueError):
            return 0
