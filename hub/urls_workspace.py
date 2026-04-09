"""URL patterns for workspace subdomains (<slug>.scitex-orochi.com)."""

import os

from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path

from hub import views

_sw_js_path = os.path.join(os.path.dirname(__file__), "static", "hub", "sw.js")


def _serve_sw(request):
    """Serve service worker at root scope (required by SW spec)."""
    try:
        with open(_sw_js_path) as f:
            return HttpResponse(f.read(), content_type="application/javascript")
    except FileNotFoundError:
        return HttpResponse("", status=404)


urlpatterns = [
    path("sw.js", _serve_sw, name="sw"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    # Dashboard (root of workspace subdomain)
    path("", views.workspace_dashboard, name="index"),
    path("settings/", views.workspace_settings_view, name="workspace-settings"),
    # Auth (workspace-scoped)
    path("signin/", views.signin_view, name="signin"),
    path("signup/", views.signup_view, name="signup"),
    path("signout/", views.signout_view, name="signout"),
    path("login/", views.signin_view, name="login"),
    path("logout/", views.signout_view, name="logout"),
    path("invite/<str:token>/", views.accept_invite_view, name="accept-invite"),
    # REST API — no slug needed, workspace from subdomain
    path("api/channels/", views.api_channels, name="api-channels"),
    path("api/messages/", views.api_messages, name="api-messages"),
    path("api/history/<str:channel_name>/", views.api_history, name="api-history"),
    path("api/stats/", views.api_stats, name="api-stats"),
    path("api/workspaces/", views.api_workspaces, name="api-workspaces"),
    path("api/github/issues/", views.github_issues, name="api-github-issues"),
    # Agent API
    path("api/agents/", views.api_agents, name="api-agents"),
    path("api/agents/purge/", views.api_agents_purge, name="api-agents-purge"),
    path("api/agents/registry/", views.api_agents_registry, name="api-agents-registry"),
    path("api/watchdog/alerts/", views.api_watchdog_alerts, name="api-watchdog-alerts"),
    path("api/events/tool-use/", views.api_event_tool_use, name="api-event-tool-use"),
    path("api/resources/", views.api_resources, name="api-resources"),
    path("api/config/", views.api_config, name="api-config"),
    # File upload
    path("api/upload", views.api_upload, name="api-upload"),
    path("api/upload-base64", views.api_upload_base64, name="api-upload-base64"),
]
