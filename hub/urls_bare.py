"""URL patterns for the bare domain (scitex-orochi.com)."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

from hub import views
from hub.views import todo_stats as _todo_stats_view

_media_url = settings.MEDIA_URL.strip("/")

urlpatterns = [
    # Media files must come before other routes
    re_path(
        rf"^{_media_url}/(?P<path>.*)$",
        static_serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    # Landing
    path("", views.landing_page, name="index"),
    path("", views.landing_page, name="landing"),
    path(
        "request-invite/",
        views.request_invite_view,
        name="request-invite",
    ),
    # Auth
    path("signin/", views.signin_view, name="signin"),
    path("signup/", views.signup_view, name="signup"),
    path("signout/", views.signout_view, name="signout"),
    path("login/", views.signin_view, name="login"),
    path("logout/", views.signout_view, name="logout"),
    # Workspace creation
    path("workspace/new/", views.create_workspace_view, name="create-workspace"),
    path("find-workspace/", views.find_workspace_view, name="find-workspace"),
    path("invite/<str:token>/", views.accept_invite_view, name="accept-invite"),
    # Backward compat — old path-based URLs redirect to subdomain
    path(
        "workspace/<slug:slug>/",
        views.redirect_old_workspace_url,
        name="workspace-dashboard",
    ),
    path(
        "workspace/<slug:slug>/settings/",
        views.redirect_old_workspace_url,
        name="workspace-settings",
    ),
    # API (bare domain)
    path("api/workspaces/", views.api_workspaces, name="api-workspaces"),
    path("api/github/issues/", views.github_issues, name="api-github-issues"),
    path(
        "api/github/issue-title/",
        views.github_issue_title,
        name="api-github-issue-title",
    ),
    # Discovery
    path("api/discover/", views.api_discover, name="api-discover"),
    # Telegram webhook
    path("webhook/telegram/", views.telegram_webhook, name="telegram-webhook"),
    # GitHub webhook
    path("webhook/github/", views.github_webhook, name="github-webhook"),
    # API endpoints needed by MCP sidecar (localhost/LAN access)
    # These mirror the workspace API routes so agents on the bare domain
    # can still hit reactions, messages, agents, etc.
    path("api/reactions/", views.api_reactions, name="api-reactions"),
    path("api/messages/", views.api_messages, name="api-messages"),
    path(
        "api/messages/<int:message_id>/",
        views.api_message_detail,
        name="api-message-detail",
    ),
    # Channel info — MCP `channel_info` tool hits this on the bare
    # domain (issue #254). Token-auth on GET handled inside the view.
    path("api/channels/", views.api_channels, name="api-channels"),
    # Channel export — MCP `export_channel` tool. Already accepts
    # ?token= internally; just needs a route on the bare domain.
    path(
        "api/channels/<str:chat_id>/export/",
        views.api_channel_export,
        name="api-channel-export",
    ),
    # Channel members — MCP `channel_members` tool (#252). Token-auth
    # on GET handled inside the view; POST/PATCH/DELETE still session-only
    # on the bare domain since admin actions need an attributable user.
    path(
        "api/channel-members/",
        views.api_channel_members,
        name="api-channel-members",
    ),
    # My subscriptions — MCP `my_subscriptions` tool (#253). Read-only,
    # token-auth via ?token=&agent=<name>.
    path(
        "api/me/subscriptions/",
        views.api_my_subscriptions,
        name="api-my-subscriptions",
    ),
    # Workspace-scoped routes — MCP sidecars build URLs of the form
    # /api/workspace/<slug>/dms/?token=wks_... when the agent's
    # SCITEX_OROCHI_URL points at the bare domain (the default for the
    # production hub). Without these the DM tool, channel listing,
    # history fetch, and per-channel export 404 (issue #258 root cause).
    # The slug kwarg is consumed by ``get_workspace`` /
    # ``resolve_workspace_and_actor`` so the same view function works on
    # both the subdomain (`request.workspace` set by middleware) and the
    # bare domain (slug from URL).
    path(
        "api/workspace/<slug:slug>/dms/",
        views.api_dms,
        name="api-dms-bare",
    ),
    path(
        "api/workspace/<slug:slug>/channels/",
        views.api_channels,
        name="api-channels-bare",
    ),
    path(
        "api/workspace/<slug:slug>/messages/",
        views.api_messages,
        name="api-messages-bare",
    ),
    path(
        "api/workspace/<slug:slug>/history/<str:channel_name>/",
        views.api_history,
        name="api-history-bare",
    ),
    path(
        "api/workspace/<slug:slug>/channels/<str:chat_id>/export/",
        views.api_channel_export,
        name="api-channel-export-bare",
    ),
    path(
        "api/workspace/<slug:slug>/channel-members/",
        views.api_channel_members,
        name="api-channel-members-bare",
    ),
    path(
        "api/workspace/<slug:slug>/me/subscriptions/",
        views.api_my_subscriptions,
        name="api-my-subscriptions-bare",
    ),
    path("api/agents/", views.api_agents, name="api-agents"),
    path("api/agents/health/", views.api_agent_health, name="api-agent-health"),
    # Fleet-wide cron status (Phase 2 msg#16406, MCP tool lead msg#16684).
    # Mounted on the bare domain too so MCP sidecars can call
    # ``/api/cron/?token=wks_...&agent=<self>`` without a subdomain.
    path("api/cron/", views.api_cron, name="api-cron-bare"),
    # Auto-dispatch operator triggers + inspection (Phase 1c msg#16477).
    path(
        "api/auto-dispatch/fire/",
        views.api_auto_dispatch_fire,
        name="api-auto-dispatch-fire-bare",
    ),
    path(
        "api/auto-dispatch/status/",
        views.api_auto_dispatch_status,
        name="api-auto-dispatch-status-bare",
    ),
    # Per-agent single-screen detail payload (todo#420 MVP).
    path(
        "api/agents/<str:name>/detail/",
        views.api_agent_detail,
        name="api-agent-detail",
    ),
    # Bun MCP sidecars POST registry heartbeats here. Must exist on the
    # bare domain because SCITEX_OROCHI_URL defaults to wss://scitex-orochi.com
    # (no subdomain). Without this entry the heartbeat 404s and the
    # Activity tab shows empty orochi_current_task / orochi_context_pct for everyone
    # (todo#155 root cause).
    path(
        "api/agents/register/",
        views.api_agents_register,
        name="api-agents-register",
    ),
    # A2A dispatch is now served by the SDK at /v1/agents/<name>/
    # (mounted in orochi/asgi.py — see hub.a2a.mount.build_a2a_app).
    # Only the WS-bridge reply callback remains Django-served.
    path(
        "api/a2a/reply/",
        views.api_a2a_reply,
        name="api-a2a-reply-bare",
    ),
    # Admin subscribe/unsubscribe — issue #262 §9.1. Mirrored on the bare
    # domain so MCP sidecars (which default to the apex) can hit the
    # admin path without a subdomain.
    path(
        "api/agents/<str:target>/subscribe/",
        views.api_admin_agent_subscribe,
        name="api-admin-agent-subscribe-bare",
    ),
    path(
        "api/agents/<str:target>/unsubscribe/",
        views.api_admin_agent_unsubscribe,
        name="api-admin-agent-unsubscribe-bare",
    ),
    # Central container-agent registry — mounted on bare domain so the MCP
    # sidecar on localhost can reach it without the subdomain middleware.
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
    path("api/upload", views.api_upload, name="api-upload"),
    path(
        "api/upload-base64",
        views.api_upload_base64,
        name="api-upload-base64",
    ),
    # Web push (todo#263) — mirrored on bare domain so PWAs installed from
    # the apex can still fetch the VAPID key and subscribe/unsubscribe.
    path("api/push/vapid-key", views.api_push_vapid_key, name="api-push-vapid-key"),
    path("api/push/subscribe", views.api_push_subscribe, name="api-push-subscribe"),
    path(
        "api/push/unsubscribe",
        views.api_push_unsubscribe,
        name="api-push-unsubscribe",
    ),
    # Public status page (issue #75)
    path("status/", views.status_page, name="status"),
    path("api/status/", views.api_status, name="api-status"),
    # TODO stats (scitex-orochi#171) — bare domain mirror so MCP sidecars +
    # localhost clients can reach the endpoint without subdomain routing.
    path("api/todo/stats/", _todo_stats_view.api_todo_stats, name="api-todo-stats"),
]
