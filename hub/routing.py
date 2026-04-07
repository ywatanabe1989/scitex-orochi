"""WebSocket URL routing for Orochi hub."""

from django.urls import re_path

from hub import consumers

websocket_urlpatterns = [
    re_path(r"ws/agent/$", consumers.AgentConsumer.as_asgi()),
    re_path(r"ws/dashboard/$", consumers.DashboardConsumer.as_asgi()),
]
