import json
import logging
import socket
import time
import uuid
from contextlib import asynccontextmanager
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event, Thread
from typing import Iterator

import redis
import redis.asyncio as async_redis
from django.conf import settings
from django.utils import timezone

from core.adapters import DokkuAdapter
from core.apps.models import App

logger = logging.getLogger(__name__)

KEY_PREFIX = 'fabroku:logstream'
SSE_KEEPALIVE_SECONDS = 15
SUBSCRIBER_TTL_SECONDS = 45
LOCK_TTL_SECONDS = 45


def get_logstream_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.CHANNEL_REDIS_URL, decode_responses=True)


def get_async_logstream_redis() -> async_redis.Redis:
    return async_redis.Redis.from_url(settings.CHANNEL_REDIS_URL, decode_responses=True)


def _apps_key() -> str:
    return f'{KEY_PREFIX}:apps'


def _subscriber_key(app_id: int, subscriber_id: str) -> str:
    return f'{KEY_PREFIX}:subscribers:{app_id}:{subscriber_id}'


def _subscriber_pattern(app_id: int) -> str:
    return f'{KEY_PREFIX}:subscribers:{app_id}:*'


def _buffer_key(app_id: int) -> str:
    return f'{KEY_PREFIX}:buffer:{app_id}'


def _channel_name(app_id: int) -> str:
    return f'{KEY_PREFIX}:channel:{app_id}'


def channel_name(app_id: int) -> str:
    return _channel_name(app_id)


def _lock_key(app_id: int) -> str:
    return f'{KEY_PREFIX}:lock:{app_id}'


def _runner_key(runner_id: str) -> str:
    return f'{KEY_PREFIX}:runner:{runner_id}'


def _runner_pattern() -> str:
    return f'{KEY_PREFIX}:runner:*'


def _now_iso() -> str:
    return timezone.now().isoformat()


def encode_event(event: str, payload: dict) -> str:
    return f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'


def request_app_stream(redis_client: redis.Redis, app_id: int) -> None:
    redis_client.sadd(_apps_key(), str(app_id))


def touch_subscriber(redis_client: redis.Redis, app_id: int, subscriber_id: str) -> None:
    redis_client.setex(_subscriber_key(app_id, subscriber_id), SUBSCRIBER_TTL_SECONDS, '1')
    request_app_stream(redis_client, app_id)


async def touch_subscriber_async(redis_client: async_redis.Redis, app_id: int, subscriber_id: str) -> None:
    await redis_client.setex(_subscriber_key(app_id, subscriber_id), SUBSCRIBER_TTL_SECONDS, '1')
    await redis_client.sadd(_apps_key(), str(app_id))


def remove_subscriber(redis_client: redis.Redis, app_id: int, subscriber_id: str) -> None:
    redis_client.delete(_subscriber_key(app_id, subscriber_id))


async def remove_subscriber_async(redis_client: async_redis.Redis, app_id: int, subscriber_id: str) -> None:
    await redis_client.delete(_subscriber_key(app_id, subscriber_id))


def count_subscribers(redis_client: redis.Redis, app_id: int) -> int:
    return sum(1 for _key in redis_client.scan_iter(_subscriber_pattern(app_id), count=100))


def get_requested_app_ids(redis_client: redis.Redis) -> list[int]:
    app_ids = []
    for value in redis_client.smembers(_apps_key()):
        try:
            app_ids.append(int(value))
        except (TypeError, ValueError):
            redis_client.srem(_apps_key(), value)
    return app_ids


def read_buffer(redis_client: redis.Redis, app_id: int) -> list[dict]:
    events = []
    for raw_payload in redis_client.lrange(_buffer_key(app_id), 0, -1):
        try:
            events.append(json.loads(raw_payload))
        except json.JSONDecodeError:
            continue
    return events


async def read_buffer_async(redis_client: async_redis.Redis, app_id: int) -> list[dict]:
    events = []
    for raw_payload in await redis_client.lrange(_buffer_key(app_id), 0, -1):
        try:
            events.append(json.loads(raw_payload))
        except json.JSONDecodeError:
            continue
    return events


def publish_line(redis_client: redis.Redis, app_id: int, line: str, *, source: str = 'runtime') -> None:
    payload = {
        'line': line,
        'source': source,
        'created_at': _now_iso(),
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    redis_client.rpush(_buffer_key(app_id), encoded)
    redis_client.ltrim(_buffer_key(app_id), -int(settings.LOG_STREAM_BUFFER_LINES), -1)
    redis_client.publish(_channel_name(app_id), json.dumps({'event': 'line', 'payload': payload}, ensure_ascii=False))


def publish_error(redis_client: redis.Redis, app_id: int, message: str) -> None:
    payload = {
        'message': message,
        'created_at': _now_iso(),
    }
    redis_client.publish(_channel_name(app_id), json.dumps({'event': 'error', 'payload': payload}, ensure_ascii=False))


def touch_runner(redis_client: redis.Redis, runner_id: str, active_apps: int) -> None:
    redis_client.setex(
        _runner_key(runner_id),
        max(LOCK_TTL_SECONDS, int(settings.LOG_STREAM_RUNNER_HEARTBEAT_SECONDS) * 3),
        json.dumps(
            {
                'runner_id': runner_id,
                'hostname': socket.gethostname(),
                'active_apps': active_apps,
                'last_heartbeat_at': _now_iso(),
            },
            ensure_ascii=False,
        ),
    )


def has_live_runner(redis_client: redis.Redis) -> bool:
    return any(True for _key in redis_client.scan_iter(_runner_pattern(), count=50))


@contextmanager
def app_stream_subscription(app_id: int) -> Iterator[tuple[redis.Redis, str]]:
    redis_client = get_logstream_redis()
    subscriber_id = str(uuid.uuid4())
    touch_subscriber(redis_client, app_id, subscriber_id)
    try:
        yield redis_client, subscriber_id
    finally:
        remove_subscriber(redis_client, app_id, subscriber_id)


@asynccontextmanager
async def async_app_stream_subscription(app_id: int):
    redis_client = get_async_logstream_redis()
    subscriber_id = str(uuid.uuid4())
    await touch_subscriber_async(redis_client, app_id, subscriber_id)
    try:
        yield redis_client, subscriber_id
    finally:
        await remove_subscriber_async(redis_client, app_id, subscriber_id)
        await redis_client.aclose()


def acquire_app_lock(redis_client: redis.Redis, app_id: int, owner: str) -> bool:
    return bool(redis_client.set(_lock_key(app_id), owner, nx=True, ex=LOCK_TTL_SECONDS))


def refresh_app_lock(redis_client: redis.Redis, app_id: int, owner: str) -> bool:
    if redis_client.get(_lock_key(app_id)) != owner:
        return False
    redis_client.expire(_lock_key(app_id), LOCK_TTL_SECONDS)
    return True


def release_app_lock(redis_client: redis.Redis, app_id: int, owner: str) -> None:
    if redis_client.get(_lock_key(app_id)) == owner:
        redis_client.delete(_lock_key(app_id))


@dataclass
class LogTailWorker:
    app_id: int
    runner_id: str
    stop_event: Event

    def run(self) -> None:
        redis_client = get_logstream_redis()
        lock_owner = f'{self.runner_id}:{uuid.uuid4()}'
        if not acquire_app_lock(redis_client, self.app_id, lock_owner):
            logger.info('Tail de logs ja esta ativo para app_id=%s.', self.app_id)
            return

        idle_since: float | None = None
        try:
            try:
                app = App.objects.get(id=self.app_id, deleted_at__isnull=True)
            except App.DoesNotExist:
                publish_error(redis_client, self.app_id, 'App nao encontrado para streaming de logs.')
                return

            if not app.name_dokku:
                publish_error(redis_client, self.app_id, 'App sem name_dokku para streaming de logs.')
                return

            adapter = DokkuAdapter(
                audit_context={
                    'origin': 'logstream',
                    'app_id': app.id,
                    'metadata': {
                        'runner_id': self.runner_id,
                    },
                }
            )

            self._seed_buffer(redis_client, app, adapter)

            def should_stop() -> bool:
                nonlocal idle_since
                if self.stop_event.is_set():
                    return True
                if not refresh_app_lock(redis_client, self.app_id, lock_owner):
                    return True
                if count_subscribers(redis_client, self.app_id) > 0:
                    idle_since = None
                    return False
                idle_since = idle_since or time.monotonic()
                return (time.monotonic() - idle_since) >= int(settings.LOG_STREAM_IDLE_SECONDS)

            for line in adapter.logs_app_tail(app.name_dokku, should_stop=should_stop):
                if line and line.strip():
                    publish_line(redis_client, self.app_id, line.strip())
        except Exception as exc:
            logger.exception('Logstream falhou para app_id=%s.', self.app_id)
            publish_error(redis_client, self.app_id, str(exc))
        finally:
            release_app_lock(redis_client, self.app_id, lock_owner)

    def _seed_buffer(self, redis_client: redis.Redis, app: App, adapter: DokkuAdapter) -> None:
        output = adapter.logs_app(app.name_dokku, num_lines=min(200, int(settings.LOG_STREAM_BUFFER_LINES)))
        for line in (output or '').splitlines():
            normalized = line.strip()
            if normalized:
                publish_line(redis_client, app.id, normalized, source='snapshot')


class LogStreamSupervisor:
    def __init__(self, runner_id: str | None = None):
        self.runner_id = runner_id or f'{socket.gethostname()}:{uuid.uuid4()}'
        self.redis_client = get_logstream_redis()
        self.stop_event = Event()
        self.threads: dict[int, Thread] = {}

    def stop(self) -> None:
        self.stop_event.set()

    def run_forever(self) -> None:
        logger.info('Runner de logstream iniciado: %s', self.runner_id)
        while not self.stop_event.is_set():
            self._reconcile()
            touch_runner(self.redis_client, self.runner_id, len(self.threads))
            time.sleep(max(1, int(settings.LOG_STREAM_RUNNER_HEARTBEAT_SECONDS)))

    def _reconcile(self) -> None:
        for app_id, thread in list(self.threads.items()):
            if not thread.is_alive():
                self.threads.pop(app_id, None)

        for app_id in get_requested_app_ids(self.redis_client):
            if count_subscribers(self.redis_client, app_id) <= 0:
                self.redis_client.srem(_apps_key(), str(app_id))
                continue
            if app_id in self.threads:
                continue
            worker = LogTailWorker(app_id=app_id, runner_id=self.runner_id, stop_event=self.stop_event)
            thread = Thread(target=worker.run, name=f'logstream-app-{app_id}', daemon=True)
            self.threads[app_id] = thread
            thread.start()
