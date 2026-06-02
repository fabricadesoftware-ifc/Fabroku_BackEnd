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

from core.apps.routing import websocket_urlpatterns  # noqa: E402
from core.apps.websocket_auth import CLITokenAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_application,
    'websocket': CLITokenAuthMiddleware(URLRouter(websocket_urlpatterns)),
})
