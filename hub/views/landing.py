"""Landing page and workspace discovery views."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from hub.models import InviteRequest, Workspace, WorkspaceMember
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


@require_POST
def request_invite_view(request):
    """Public endpoint — accept an invite-request form from the landing
    page and queue a pending InviteRequest row. Admins review pending
    requests in Workspace Settings → Approve creates a WorkspaceInvitation
    + shares the URL; Deny flags the row. Replaces the Option A mailto
    CTA with an in-app form so requests are tracked.

    Rate-limit enforcement is intentionally basic here (de-dup on
    pending+email); richer throttling belongs at the web-proxy layer.
    """
    email = (request.POST.get("email") or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        messages.error(request, "A valid email address is required.")
        return redirect("landing")
    name = (request.POST.get("name") or "").strip()[:150]
    affiliation = (request.POST.get("affiliation") or "").strip()[:200]
    message = (request.POST.get("message") or "").strip()[:2000]
    requested_workspace = (request.POST.get("workspace") or "").strip().lower()[:100]
    existing = InviteRequest.objects.filter(
        email=email, status=InviteRequest.STATUS_PENDING
    ).first()
    if existing:
        messages.info(
            request,
            "We already have a pending request for that email — an admin "
            "will reach out soon.",
        )
        return redirect("landing")
    InviteRequest.objects.create(
        email=email,
        name=name,
        affiliation=affiliation,
        message=message,
        requested_workspace=requested_workspace,
    )
    messages.success(
        request,
        "Thanks — your request is in the queue. An admin will email you once "
        "it is approved.",
    )
    return redirect("landing")
