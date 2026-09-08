import json
import re
from urllib.parse import urlparse

from django.conf import settings
from mcp.server.transport_security import TransportSecuritySettings

from mcp_server.auth import resolve_cli_token
from mcp_server.tools import mcp

MCP_PATH_RE = re.compile(r'^/api/mcp/(?P<token>[^/]+)(?P<remainder>/.*)?$')

_backend_host = urlparse(settings.BACKEND_URL).hostname or 'localhost'

_mcp_asgi_app = mcp.streamable_http_app(
    streamable_http_path='/',
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=[_backend_host, f'{_backend_host}:*'],
    ),
)


async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode('utf-8')
    await send({
        'type': 'http.response.start',
        'status': status,
        'headers': [(b'content-type', b'application/json')],
    })
    await send({'type': 'http.response.body', 'body': body})


def match_mcp_path(path: str) -> re.Match[str] | None:
    return MCP_PATH_RE.match(path)


async def handle_mcp_request(scope, receive, send, match: re.Match[str]) -> None:
    token = match.group('token')
    remainder = match.group('remainder') or '/'

    user = await resolve_cli_token(token)
    if user is None:
        await _send_json(send, 401, {'error': 'Token CLI inválido, revogado ou ausente.'})
        return

    scope = dict(scope)
    scope['path'] = remainder
    scope['raw_path'] = remainder.encode('utf-8')
    scope['state'] = {'fabroku_user': user}
    await _mcp_asgi_app(scope, receive, send)
