"""URL configuration for the hub app."""

from django.contrib.auth import views as auth_views
from django.urls import path

from hub import views

urlpatterns = [
    # Auth
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="hub/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Dashboard
    path("", views.index, name="index"),
    path(
        "workspace/<slug:slug>/", views.workspace_dashboard, name="workspace-dashboard"
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
]
