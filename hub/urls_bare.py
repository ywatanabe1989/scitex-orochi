"""URL patterns for the bare domain (scitex-orochi.com)."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

from hub import views

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
    path("api/agents/", views.api_agents, name="api-agents"),
    path("api/upload", views.api_upload, name="api-upload"),
    path(
        "api/upload-base64",
        views.api_upload_base64,
        name="api-upload-base64",
    ),
]
