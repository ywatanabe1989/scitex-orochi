"""URL patterns for workspace subdomains (<slug>.scitex-orochi.com)."""

import os

from django.conf import settings as _dj_settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve as _serve_media

from hub import views
from hub.views import todo_stats as _todo_stats_view

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
    path(
        "api/channels/<str:chat_id>/export/",
        views.api_channel_export,
        name="api-channel-export",
    ),
    # Channel rename (todo#71 drag-to-move + folder rename).
    # rename-prefix/ must come before <int:channel_id>/rename/ so the
    # literal "rename-prefix" isn't parsed as an integer id.
    path(
        "api/channels/rename-prefix/",
        views.api_channel_rename_prefix,
        name="api-channel-rename-prefix",
    ),
    path(
        "api/channels/<int:channel_id>/rename/",
        views.api_channel_rename,
        name="api-channel-rename",
    ),
    path("api/channel-prefs/", views.api_channel_prefs, name="api-channel-prefs"),
    path("api/channel-members/", views.api_channel_members, name="api-channel-members"),
    # My subscriptions — MCP `my_subscriptions` tool (#253). Read-only.
    path(
        "api/me/subscriptions/",
        views.api_my_subscriptions,
        name="api-my-subscriptions",
    ),
    path("api/messages/", views.api_messages, name="api-messages"),
    path("api/invitations/", views.api_invitations, name="api-invitations"),
    path(
        "api/invitations/<str:token>/",
        views.api_invitation_detail,
        name="api-invitation-detail",
    ),
    path("api/dms/", views.api_dms, name="api-dms"),
    path("api/history/<str:channel_name>/", views.api_history, name="api-history"),
    path("api/stats/", views.api_stats, name="api-stats"),
    path("api/workspaces/", views.api_workspaces, name="api-workspaces"),
    path("api/github/issues/", views.github_issues, name="api-github-issues"),
    path(
        "api/github/issue-title/",
        views.github_issue_title,
        name="api-github-issue-title",
    ),
    # Agent API
    path("api/agents/", views.api_agents, name="api-agents"),
    path("api/agents/purge/", views.api_agents_purge, name="api-agents-purge"),
    path("api/agents/restart/", views.api_agents_restart, name="api-agents-restart"),
    path("api/agents/kill/", views.api_agents_kill, name="api-agents-kill"),
    path("api/agents/register/", views.api_agents_register, name="api-agents-register"),
    path("api/agents/registry/", views.api_agents_registry, name="api-agents-registry"),
    # Orochi unified cron Phase 2 (msg#16406 / msg#16408) — mounted on
    # the workspace subdomain so dashboard sessions on ``<slug>.scitex-
    # orochi.com`` can fetch it without the ``/workspace/<slug>/`` prefix.
    path("api/cron/", views.api_cron, name="api-cron-ws"),
    # Auto-dispatch operator triggers + inspection (Phase 1c msg#16477).
    path(
        "api/auto-dispatch/fire/",
        views.api_auto_dispatch_fire,
        name="api-auto-dispatch-fire-ws",
    ),
    path(
        "api/auto-dispatch/status/",
        views.api_auto_dispatch_status,
        name="api-auto-dispatch-status-ws",
    ),
    # Admin-scoped subscribe/unsubscribe (issue #262 §9.1) — mounted on
    # the workspace subdomain so dashboard sessions on
    # ``<slug>.scitex-orochi.com`` can call the admin path without an
    # explicit slug. Permission gate inside the view enforces admin/staff.
    path(
        "api/agents/<str:target>/subscribe/",
        views.api_admin_agent_subscribe,
        name="api-admin-agent-subscribe-ws",
    ),
    path(
        "api/agents/<str:target>/unsubscribe/",
        views.api_admin_agent_unsubscribe,
        name="api-admin-agent-unsubscribe-ws",
    ),
    # Per-agent single-screen detail payload (todo#420 MVP).
    path(
        "api/agents/<str:name>/detail/",
        views.api_agent_detail,
        name="api-agent-detail",
    ),
    path(
        "api/subagents/update/", views.api_subagents_update, name="api-subagents-update"
    ),
    path("api/agents/health/", views.api_agent_health, name="api-agent-health"),
    path("api/agent-profiles/", views.api_agent_profiles, name="api-agent-profiles"),
    path("api/agents/avatar/", views.api_agents_avatar, name="api-agents-avatar"),
    # Pin/unpin — keeps agent visible as ghost when offline + floats to top.
    # Mirrors hub/urls.py; was missing here so POST /api/agents/pin/ silently
    # 404'd on workspace subdomains (ywatanabe reported 2026-04-19: "pin can
    # be clickable; however, it does not change anything"). The frontend was
    # flipping the class optimistically but the API call never persisted.
    path("api/agents/pin/", views.api_agents_pin, name="api-agents-pin"),
    path("api/agents/pinned/", views.api_agents_pinned, name="api-agents-pinned"),
    # Per-user (human) profile + avatar — todo#50
    path("api/user-profile/", views.api_user_profile, name="api-user-profile"),
    path(
        "api/user-profile/avatar/",
        views.api_user_profile_avatar,
        name="api-user-profile-avatar",
    ),
    path(
        "api/workspace-members/avatars/",
        views.api_workspace_member_avatars,
        name="api-workspace-member-avatars",
    ),
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
    path(
        "api/messages/<int:message_id>/translate/",
        views.api_message_translate,
        name="api-message-translate",
    ),
    path("api/releases/", views.api_releases, name="api-releases"),
    path(
        "api/repo/<str:owner>/<str:repo>/changelog/",
        views.api_repo_changelog,
        name="api-repo-changelog",
    ),
    # Tracked repos CRUD (todo#90) + reorder (todo#91)
    path(
        "api/tracked-repos/",
        views.api_tracked_repos,
        name="api-tracked-repos",
    ),
    path(
        "api/tracked-repos/reorder/",
        views.api_tracked_repos_reorder,
        name="api-tracked-repos-reorder",
    ),
    path(
        "api/tracked-repos/<int:repo_id>/",
        views.api_tracked_repo_detail,
        name="api-tracked-repo-detail",
    ),
    path("api/threads/", views.api_threads, name="api-threads"),
    path("api/resources/", views.api_resources, name="api-resources"),
    path("api/todo/stats/", _todo_stats_view.api_todo_stats, name="api-todo-stats"),
    path("api/config/", views.api_config, name="api-config"),
    # Discovery
    path("api/discover/", views.api_discover, name="api-discover"),
    # File upload
    path("api/upload", views.api_upload, name="api-upload"),
    path("api/upload-base64", views.api_upload_base64, name="api-upload-base64"),
    # Web push (todo#263)
    path("api/push/vapid-key", views.api_push_vapid_key, name="api-push-vapid-key"),
    path("api/push/subscribe", views.api_push_subscribe, name="api-push-subscribe"),
    path(
        "api/push/unsubscribe", views.api_push_unsubscribe, name="api-push-unsubscribe"
    ),
    # Telegram webhook
    path("webhook/telegram/", views.telegram_webhook, name="telegram-webhook"),
]
