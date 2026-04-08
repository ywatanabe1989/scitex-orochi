"""URL patterns for workspace subdomains (<slug>.scitex-orochi.com)."""

from django.contrib import admin
from django.urls import include, path

from hub import views

urlpatterns = [
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
]
