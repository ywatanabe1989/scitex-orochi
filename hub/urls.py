"""URL configuration for the hub app."""

from django.urls import path

from hub import views

urlpatterns = [
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
        "api/workspace/<slug:slug>/messages/", views.api_messages, name="api-messages"
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
    path("api/agents/registry/", views.api_agents_registry, name="api-agents-registry"),
    path("api/resources/", views.api_resources, name="api-resources"),
]
