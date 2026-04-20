"""WebSocket URL routing for Orochi hub."""

from django.urls import re_path

from hub import consumers, terminal_consumers

websocket_urlpatterns = [
    re_path(r"ws/agent/$", consumers.AgentConsumer.as_asgi()),
    re_path(r"ws/dashboard/$", consumers.DashboardConsumer.as_asgi()),
    # todo#47 — web terminal (xterm.js <-> local PTY or asyncssh session)
    re_path(
        r"ws/terminal/(?P<host>[a-zA-Z0-9._-]+)/$",
        terminal_consumers.TerminalConsumer.as_asgi(),
    ),
]
