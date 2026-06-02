from django.urls import path

from core.apps.consumers import InteractiveSessionConsumer

websocket_urlpatterns = [
    path(
        'ws/apps/apps/<int:app_id>/interactive_sessions/<uuid:session_id>/',
        InteractiveSessionConsumer.as_asgi(),
    ),
]
