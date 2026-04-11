"""URL patterns for workspace subdomains (<slug>.scitex-orochi.com)."""

import os

from django.conf import settings as _dj_settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve as _serve_media

from hub import views

_sw_js_path = os.path.join(os.path.dirname(__file__), "static", "hub", "sw.js")


def _serve_sw(request):
    """Serve service worker at root scope (required by SW spec)."""
    try:
        with open(_sw_js_path) as f:
            return HttpResponse(f.read(), content_type="application/javascript")
    except FileNotFoundError:
        return HttpResponse("", status=404)


_media_url_ws = _dj_settings.MEDIA_URL.strip("/")

urlpatterns = [
    path("sw.js", _serve_sw, name="sw"),
    # Media must come before the workspace catchall/root routes below so
    # uploaded files under /media/... are served on workspace subdomains.
    re_path(
        rf"^{_media_url_ws}/(?P<path>.*)$",
        _serve_media,
        {"document_root": _dj_settings.MEDIA_ROOT},
    ),
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
    path("agent-login/", views.agent_login_view, name="agent-login"),
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
    path("api/agents/restart/", views.api_agents_restart, name="api-agents-restart"),
    path("api/agents/register/", views.api_agents_register, name="api-agents-register"),
    path("api/agents/registry/", views.api_agents_registry, name="api-agents-registry"),
    path(
        "api/subagents/update/", views.api_subagents_update, name="api-subagents-update"
    ),
    path("api/agents/health/", views.api_agent_health, name="api-agent-health"),
    path("api/agent-profiles/", views.api_agent_profiles, name="api-agent-profiles"),
    path("api/agents/avatar/", views.api_agents_avatar, name="api-agents-avatar"),
    path("api/watchdog/alerts/", views.api_watchdog_alerts, name="api-watchdog-alerts"),
    path("api/events/tool-use/", views.api_event_tool_use, name="api-event-tool-use"),
    path("api/connectivity/", views.api_connectivity, name="api-connectivity"),
    path("api/media/", views.api_media, name="api-media"),
    path("api/members/", views.api_members, name="api-members"),
    path("api/reactions/", views.api_reactions, name="api-reactions"),
    path("api/releases/", views.api_releases, name="api-releases"),
    path("api/threads/", views.api_threads, name="api-threads"),
    path("api/resources/", views.api_resources, name="api-resources"),
    path("api/config/", views.api_config, name="api-config"),
    # Discovery
    path("api/discover/", views.api_discover, name="api-discover"),
    # File upload
    path("api/upload", views.api_upload, name="api-upload"),
    path("api/upload-base64", views.api_upload_base64, name="api-upload-base64"),
    # Telegram webhook
    path("webhook/telegram/", views.telegram_webhook, name="telegram-webhook"),
]
