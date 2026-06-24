import asyncio
import json
import time
import uuid

from django.conf import settings
from django.http import StreamingHttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response

from core.adapters import DokkuAdapter
from core.apps.models import App
from core.logs.logstream import (
    SSE_KEEPALIVE_SECONDS,
    channel_name,
    encode_event,
    get_async_logstream_redis,
    get_logstream_redis,
    has_live_runner,
    read_buffer_async,
    remove_subscriber_async,
    touch_subscriber_async,
)
from core.logs.ssh_audit import ssh_audit_context

from .models import AppLog
from .serializers import AppLogSerializer


class ServerSentEventRenderer(BaseRenderer):
    """Renderer usado apenas para liberar content negotiation de streams SSE."""

    media_type = 'text/event-stream'
    format = 'event-stream'
    charset = 'utf-8'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b''
        if isinstance(data, bytes):
            return data
        return json.dumps(data).encode(self.charset)


def _has_global_access(user) -> bool:
    """Retorna True para perfis com visibilidade administrativa global."""
    return bool(getattr(user, 'is_superuser', False))


@extend_schema(tags=['logs'])
class AppLogViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para visualização de logs de aplicações."""

    queryset = AppLog.objects.all()
    serializer_class = AppLogSerializer
    filterset_fields = ['level', 'category', 'task_id', 'app', 'progress']
    search_fields = ['message', 'task_id']
    ordering_fields = ['created_at', 'level', 'progress']
    ordering = ['-created_at']

    def get_queryset(self):  # type: ignore
        """Retorna logs apenas das apps do usuário."""
        if self.request.user.is_anonymous:
            return AppLog.objects.none()
        if _has_global_access(self.request.user):
            return AppLog.objects.all().select_related('app')
        return AppLog.objects.filter(app__project__users=self.request.user).distinct().select_related('app')

    @action(detail=False, methods=['get'], url_path='stream/(?P<task_id>[^/.]+)')
    def stream(self, request, task_id=None):
        """
        Polling de logs em tempo real.
        Query params: ?after={last_id} para pegar logs novos.
        """
        base_queryset = self.get_queryset().filter(task_id=task_id)

        after_id = request.query_params.get('after')
        if after_id:
            base_queryset = base_queryset.filter(id__gt=int(after_id))

        queryset = base_queryset.order_by('created_at')
        serializer = self.get_serializer(queryset, many=True)
        logs = serializer.data

        return Response({
            'logs': logs,
            'last_id': logs[-1]['id'] if logs else after_id,
            'count': len(logs),
            'user_id': getattr(request.user, 'id', None),
            'user_email': getattr(request.user, 'email', None),
            'is_superuser': getattr(request.user, 'is_superuser', False),
            'is_anonymous': getattr(request.user, 'is_anonymous', True),
        })

    @action(detail=False, methods=['get'], url_path='app-runtime')
    def app_runtime(self, request):
        """
        Logs em tempo real do container (stdout/stderr do app).
        Query params: ?app={app_id}&num={number}.
        """
        app_id = request.query_params.get('app')
        if not app_id:
            return Response({'error': 'Parâmetro app é obrigatório'}, status=400)

        try:
            app = App.objects.select_related('project').get(id=app_id)
        except App.DoesNotExist:
            return Response({'error': 'App não encontrado'}, status=404)

        if not _has_global_access(request.user) and not app.project.users.filter(id=request.user.id).exists():
            return Response({'error': 'Sem permissão'}, status=403)

        if not app.name_dokku:
            return Response({'lines': [], 'message': 'App sem name_dokku'})

        num = min(int(request.query_params.get('num', 200)), 500)
        try:
            with ssh_audit_context(
                origin='http.app_runtime',
                user_id=getattr(request.user, 'id', None),
                app_id=app.id,
            ):
                dokku = DokkuAdapter()
                output = dokku.logs_app(app.name_dokku, num_lines=num)
            lines = [ln.strip() for ln in (output or '').split('\n') if ln.strip()]
        except Exception as e:
            return Response({'lines': [], 'error': str(e)}, status=500)

        return Response({'lines': lines})

    @action(
        detail=False,
        methods=['get'],
        url_path='app-runtime-stream',
        renderer_classes=[ServerSentEventRenderer, JSONRenderer],
    )
    def app_runtime_stream(self, request):
        """
        Stream SSE dos logs runtime do app.
        Query params: ?app={app_id}&tail={number}.
        """
        app_id = request.query_params.get('app')
        if not settings.LOG_STREAM_SSE_ENABLED:
            return Response({'error': 'Streaming SSE de logs desativado'}, status=503)
        if not app_id:
            return Response({'error': 'ParÃ¢metro app Ã© obrigatÃ³rio'}, status=400)

        try:
            app = App.objects.select_related('project').get(id=app_id)
        except App.DoesNotExist:
            return Response({'error': 'App nÃ£o encontrado'}, status=404)

        if not _has_global_access(request.user) and not app.project.users.filter(id=request.user.id).exists():
            return Response({'error': 'Sem permissÃ£o'}, status=403)

        if not app.name_dokku:
            return Response({'error': 'App sem name_dokku'}, status=400)

        redis_client = get_logstream_redis()
        if not has_live_runner(redis_client):
            return Response({'error': 'Logstream indisponÃ­vel'}, status=503)

        try:
            tail = min(max(int(request.query_params.get('tail', 200)), 1), 500)
        except ValueError:
            tail = 200

        async def event_stream():
            redis_client = get_async_logstream_redis()
            subscriber_id = str(uuid.uuid4())
            pubsub = None
            try:
                await touch_subscriber_async(redis_client, app.id, subscriber_id)
                pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
                await pubsub.subscribe(channel_name(app.id))
                keepalive_at = time.monotonic()

                buffer_events = (await read_buffer_async(redis_client, app.id))[-tail:]
                yield encode_event(
                    'snapshot',
                    {
                        'lines': [event.get('line', '') for event in buffer_events if event.get('line')],
                        'count': len(buffer_events),
                    },
                )

                while True:
                    await touch_subscriber_async(redis_client, app.id, subscriber_id)
                    message = await pubsub.get_message(timeout=1)
                    if message and message.get('type') == 'message':
                        try:
                            decoded = json.loads(message.get('data') or '{}')
                        except json.JSONDecodeError:
                            continue
                        event_name = decoded.get('event') or 'line'
                        payload = decoded.get('payload') or {}
                        yield encode_event(event_name, payload)
                        keepalive_at = time.monotonic()
                        continue

                    if time.monotonic() - keepalive_at >= SSE_KEEPALIVE_SECONDS:
                        keepalive_at = time.monotonic()
                        yield encode_event('heartbeat', {'created_at': time.time()})
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            finally:
                if pubsub is not None:
                    await pubsub.aclose()
                await remove_subscriber_async(redis_client, app.id, subscriber_id)
                await redis_client.aclose()

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response
