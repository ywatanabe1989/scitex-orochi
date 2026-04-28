"""ASGI config for Orochi — routes HTTP and WebSocket.

HTTP requests with a path under ``/v1/agents/`` are forwarded to the
official a2a-sdk Starlette sub-app (see :mod:`hub.a2a.mount`); every
other HTTP request hits Django as before. WebSocket routing is
unchanged.
"""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orochi.settings")

django_asgi_app = get_asgi_application()

from hub.a2a.mount import build_a2a_app  # noqa: E402
from hub.routing import websocket_urlpatterns  # noqa: E402

_a2a_app = build_a2a_app()


async def _http_router(scope, receive, send):
    """Dispatch ``/v1/agents/...`` to the SDK Starlette app, else Django."""
    path: str = scope.get("path", "")
    if path.startswith("/v1/agents/"):
        return await _a2a_app(scope, receive, send)
    return await django_asgi_app(scope, receive, send)


application = ProtocolTypeRouter(
    {
        "http": _http_router,
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
