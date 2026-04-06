"""Landing page and workspace discovery views."""

from django.contrib import messages
from django.shortcuts import redirect, render

from hub.models import Workspace, WorkspaceMember
from hub.views._helpers import workspace_url


def landing_page(request):
    """Bare domain landing — create or find your workspace."""
    if request.user.is_authenticated:
        membership = WorkspaceMember.objects.filter(user=request.user).first()
        if membership:
            return redirect(workspace_url(membership.workspace.name))
    return render(request, "hub/landing.html")


def find_workspace_view(request):
    """Enter workspace name to navigate to its subdomain."""
    if request.method == "POST":
        name = request.POST.get("name", "").strip().lower()
        if Workspace.objects.filter(name=name).exists():
            return redirect(workspace_url(name))
        messages.error(request, "Workspace not found.")
    return render(request, "hub/find_workspace.html")


def redirect_old_workspace_url(request, slug):
    """301 redirect old /workspace/<slug>/ URLs to subdomain."""
    return redirect(workspace_url(slug), permanent=True)
