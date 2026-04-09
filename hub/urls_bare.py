"""URL patterns for the bare domain (scitex-orochi.com)."""

from django.contrib import admin
from django.urls import include, path

from hub import views

urlpatterns = [
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
]
