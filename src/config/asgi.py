"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

django_asgi_application = get_asgi_application()

from core.apps.websocket_auth import CLITokenAuthMiddleware  # noqa: E402
from interactive_sessions.routing import websocket_urlpatterns  # noqa: E402
from mcp_server.asgi import handle_mcp_request, match_mcp_path  # noqa: E402
from mcp_server.tools import mcp  # noqa: E402


async def http_application(scope, receive, send):
    match = match_mcp_path(scope['path'])
    if match:
        await handle_mcp_request(scope, receive, send, match)
        return
    await django_asgi_application(scope, receive, send)


async def _run_lifespan(receive, send):
    async with mcp.session_manager.run():
        await send({'type': 'lifespan.startup.complete'})
        while True:
            message = await receive()
            if message['type'] == 'lifespan.shutdown':
                await send({'type': 'lifespan.shutdown.complete'})
                return


async def lifespan_application(scope, receive, send):
    message = await receive()
    assert message['type'] == 'lifespan.startup'
    try:
        await _run_lifespan(receive, send)
    except Exception as exc:
        await send({'type': 'lifespan.startup.failed', 'message': str(exc)})
        raise


application = ProtocolTypeRouter({
    'http': http_application,
    'websocket': CLITokenAuthMiddleware(URLRouter(websocket_urlpatterns)),
    'lifespan': lifespan_application,
})
