import asyncio
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from core.apps.interactive_crypto import decrypt_interactive_text
from core.apps.mixins.apps.interactive_run import (
    get_interactive_session_group_name,
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


class InteractiveSessionConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        self.app_id = int(self.scope['url_route']['kwargs']['app_id'])
        self.session_id = str(self.scope['url_route']['kwargs']['session_id'])
        self.group_name = get_interactive_session_group_name(self.session_id)

        self.session = await _get_session_snapshot(self.app_id, self.session_id, user.id)
        if not self.session:
            await self.close(code=4404)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({
            'type': 'status',
            'status': self.session['status'],
            'message': 'Conectado a sessao interativa.',
        })
        self.replay_task = asyncio.create_task(self._replay_existing_messages())

    async def disconnect(self, close_code):
        replay_task = getattr(self, 'replay_task', None)
        if replay_task and not replay_task.done():
            replay_task.cancel()
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        message_type = content.get('type')

        try:
            if message_type == 'answer':
                await _submit_answer(
                    self.session_id,
                    str(content.get('prompt_id') or ''),
                    str(content.get('value') if content.get('value') is not None else ''),
                )
                await self.send_json({'type': 'ack', 'action': 'answer'})
                return

            if message_type == 'input':
                input_data = str(content.get('data') if content.get('data') is not None else '')
                if input_data:
                    chunk = await _queue_input(self.session_id, input_data)
                    await self.send_json({'type': 'ack', 'action': 'input', 'chunk_id': chunk.id})
                return

            if message_type == 'cancel':
                await _cancel_session(self.session_id)
                await self.send_json({'type': 'ack', 'action': 'cancel'})
                return

            if message_type == 'ping':
                await self.send_json({'type': 'pong'})
                return

            await self.send_json({'type': 'error', 'message': 'Mensagem WebSocket nao suportada.'})
        except ValueError as exc:
            await self.send_json({'type': 'error', 'message': str(exc)})

    async def interactive_event(self, event):
        await self.send_json({
            'type': event['event_type'],
            'id': event['event_id'],
            **event.get('payload', {}),
        })

    async def interactive_terminal_output(self, event):
        await self.send_json({
            'type': 'terminal.output',
            'output_id': event['output_id'],
            'sequence': event['sequence'],
            'content': event['content'],
        })

    async def _replay_existing_messages(self):
        query = parse_qs(self.scope.get('query_string', b'').decode('utf-8', errors='ignore'))
        after_event = self._query_int(query, 'after_event')
        after_output = self._query_int(query, 'after_output')
        messages = await _load_replay_messages(
            self.session_id,
            self.session['command_kind'],
            after_event,
            after_output,
        )
        for message in messages:
            await self.send_json(message)

    @staticmethod
    def _query_int(query: dict, key: str) -> int:
        try:
            return int((query.get(key) or ['0'])[0] or 0)
        except (TypeError, ValueError):
            return 0
