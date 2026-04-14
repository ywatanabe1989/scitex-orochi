"""URL configuration for the hub app."""

import os

from django.conf import settings
from django.http import HttpResponse
from django.urls import path, re_path
from django.views.static import serve as static_serve

from hub import views

_sw_js_path = os.path.join(os.path.dirname(__file__), "static", "hub", "sw.js")


def _serve_sw(request):
    """Serve service worker at root scope (required by SW spec)."""
    try:
        with open(_sw_js_path) as f:
            return HttpResponse(f.read(), content_type="application/javascript")
    except FileNotFoundError:
        return HttpResponse("", status=404)


_media_url = settings.MEDIA_URL.strip("/")

urlpatterns = [
    # Service worker must be at root for proper scope
    path("sw.js", _serve_sw, name="sw"),
    # Media files (uploaded images, attachments)
    re_path(
        rf"^{_media_url}/(?P<path>.*)$",
        static_serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
    # Auth
    path("signin/", views.signin_view, name="signin"),
    path("signup/", views.signup_view, name="signup"),
    path("signout/", views.signout_view, name="signout"),
    # Backward compat
    path("login/", views.signin_view, name="login"),
    path("logout/", views.signout_view, name="logout"),
    # Dashboard
    path("", views.index, name="index"),
    path("invite/<str:token>/", views.accept_invite_view, name="accept-invite"),
    path("workspace/new/", views.create_workspace_view, name="create-workspace"),
    path(
        "workspace/<slug:slug>/", views.workspace_dashboard, name="workspace-dashboard"
    ),
    path(
        "workspace/<slug:slug>/settings/",
        views.workspace_settings_view,
        name="workspace-settings",
    ),
    # REST API
    path("api/workspaces/", views.api_workspaces, name="api-workspaces"),
    path(
        "api/workspace/<slug:slug>/channels/", views.api_channels, name="api-channels"
    ),
    path(
        "api/workspace/<slug:slug>/channel-prefs/", views.api_channel_prefs, name="api-channel-prefs"
    ),
    path(
        "api/workspace/<slug:slug>/messages/", views.api_messages, name="api-messages"
    ),
    path(
        "api/workspace/<slug:slug>/dms/", views.api_dms, name="api-dms"
    ),
    path(
        "api/workspace/<slug:slug>/history/<str:channel_name>/",
        views.api_history,
        name="api-history",
    ),
    path("api/workspace/<slug:slug>/stats/", views.api_stats, name="api-stats"),
    # Agent API
    path("api/agents/", views.api_agents, name="api-agents"),
    path("api/agents/purge/", views.api_agents_purge, name="api-agents-purge"),
    path("api/agents/restart/", views.api_agents_restart, name="api-agents-restart"),
    path("api/agents/kill/", views.api_agents_kill, name="api-agents-kill"),
    path("api/agents/pin/", views.api_agents_pin, name="api-agents-pin"),
    path("api/agents/pinned/", views.api_agents_pinned, name="api-agents-pinned"),
    path("api/agents/register/", views.api_agents_register, name="api-agents-register"),
    path("api/agents/registry/", views.api_agents_registry, name="api-agents-registry"),
    # Per-agent single-screen detail payload (todo#420 MVP).
    path(
        "api/agents/<str:name>/detail/",
        views.api_agent_detail,
        name="api-agent-detail",
    ),
    # Central container-agent registry (replaces ~/.scitex/agent-container/registry/)
    path(
        "api/registry/agents/",
        views.api_registry_agents,
        name="api-registry-agents",
    ),
    path(
        "api/registry/agents/<str:name>/",
        views.api_registry_agent_detail,
        name="api-registry-agent-detail",
    ),
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
    path(
        "api/messages/<int:message_id>/",
        views.api_message_detail,
        name="api-message-detail",
    ),
    path("api/releases/", views.api_releases, name="api-releases"),
    path(
        "api/repo/<str:owner>/<str:repo>/changelog/",
        views.api_repo_changelog,
        name="api-repo-changelog",
    ),
    path("api/threads/", views.api_threads, name="api-threads"),
    path("api/resources/", views.api_resources, name="api-resources"),
    # Discovery
    path("api/discover/", views.api_discover, name="api-discover"),
    # File upload
    path("api/upload", views.api_upload, name="api-upload"),
    path("api/upload-base64", views.api_upload_base64, name="api-upload-base64"),
    path("api/media/by-hash/<str:content_hash>", views.api_media_by_hash, name="api-media-by-hash"),
    # Web push (todo#263)
    path("api/push/vapid-key", views.api_push_vapid_key, name="api-push-vapid-key"),
    path("api/push/subscribe", views.api_push_subscribe, name="api-push-subscribe"),
    path(
        "api/push/unsubscribe", views.api_push_unsubscribe, name="api-push-unsubscribe"
    ),
    # Fleet reporting
    path("api/fleet/report", views.fleet_report, name="fleet_report"),
    path("api/fleet/state", views.fleet_state, name="fleet_state"),
    # GitHub API proxy (blockers sidebar + todo tab)
    path("api/github/issues", views.github_issues, name="api-github-issues"),
    path("api/github/issue-title/", views.github_issue_title, name="api-github-issue-title"),
    # Telegram webhook
    path("webhook/telegram/", views.telegram_webhook, name="telegram-webhook"),
    # GitHub webhook
    path("webhook/github/", views.github_webhook, name="github-webhook"),
    # Scheduled actions (issue #95)
    path("api/scheduled/", views.api_scheduled, name="api-scheduled"),
    # Public status page (issue #75)
    path("status/", views.status_page, name="status"),
    path("api/status/", views.api_status, name="api-status"),
]
