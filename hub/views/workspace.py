"""Workspace dashboard and settings views (served on subdomain)."""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import render
from django.utils import timezone

from hub.models import Channel, Message, WorkspaceMember
from hub.views._helpers import get_workspace, workspace_url


@login_required
def workspace_dashboard(request):
    """Main dashboard view for a workspace (served on subdomain)."""
    workspace = get_workspace(request)

    if not request.user.is_superuser:
        if not WorkspaceMember.objects.filter(
            user=request.user, workspace=workspace
        ).exists():
            return render(request, "hub/no_access.html", status=403)

    channels = Channel.objects.filter(workspace=workspace).order_by("name")
    members = WorkspaceMember.objects.filter(workspace=workspace).select_related("user")
    is_admin = (
        request.user.is_superuser
        or WorkspaceMember.objects.filter(
            user=request.user, workspace=workspace, role="admin"
        ).exists()
    )

    # Discover agents: distinct message senders from the last 24 hours
    # who are not workspace members (human users).
    member_usernames = set(members.values_list("user__username", flat=True))
    since = timezone.now() - timedelta(hours=24)
    agent_senders = (
        Message.objects.filter(workspace=workspace, ts__gte=since)
        .values_list("sender", flat=True)
        .distinct()
    )
    agents = sorted(
        name for name in agent_senders if name not in member_usernames
    )

    return render(
        request,
        "hub/dashboard.html",
        {
            "workspace": workspace,
            "channels": channels,
            "members": members,
            "agents": agents,
            "is_admin": is_admin,
        },
    )


@login_required
def workspace_settings_view(request):
    """Workspace settings — manage tokens, members."""
    workspace = get_workspace(request)

    membership = WorkspaceMember.objects.filter(
        user=request.user, workspace=workspace
    ).first()
    if not request.user.is_superuser and (not membership or membership.role != "admin"):
        return render(request, "hub/no_access.html", status=403)

    from hub.models import WorkspaceInvitation, WorkspaceToken

    if request.method == "POST":
        _handle_settings_post(request, workspace)

    tokens = WorkspaceToken.objects.filter(workspace=workspace)
    members = WorkspaceMember.objects.filter(workspace=workspace).select_related("user")
    invitations = WorkspaceInvitation.objects.filter(
        workspace=workspace, accepted=False
    )
    return render(
        request,
        "hub/workspace_settings.html",
        {
            "workspace": workspace,
            "tokens": tokens,
            "members": members,
            "invitations": invitations,
        },
    )


def _handle_settings_post(request, workspace):
    """Process POST actions on workspace settings page."""
    from hub.models import WorkspaceInvitation, WorkspaceToken

    action = request.POST.get("action")
    if action == "create_token":
        label = request.POST.get("label", "").strip() or "agent"
        token = WorkspaceToken.objects.create(workspace=workspace, label=label)
        messages.success(request, f"Token created: {token.token}")
    elif action == "revoke_token":
        token_id = request.POST.get("token_id")
        WorkspaceToken.objects.filter(id=token_id, workspace=workspace).delete()
        messages.success(request, "Token revoked.")
    elif action == "add_member":
        username = request.POST.get("username", "").strip()
        try:
            user = User.objects.get(username=username)
            WorkspaceMember.objects.get_or_create(
                workspace=workspace, user=user, defaults={"role": "member"}
            )
            messages.success(request, f"Added {username} to workspace.")
        except User.DoesNotExist:
            messages.error(request, f"User '{username}' not found.")
    elif action == "invite_email":
        email = request.POST.get("email", "").strip()
        if email:
            invite, created = WorkspaceInvitation.objects.get_or_create(
                workspace=workspace,
                email=email,
                defaults={"invited_by": request.user},
            )
            if created:
                invite_link = workspace_url(workspace.name, f"/invite/{invite.token}/")
                try:
                    from django.core.mail import send_mail

                    send_mail(
                        subject=f"Invitation to {workspace.name} on Orochi",
                        message=(
                            f"You've been invited to join '{workspace.name}' "
                            f"on Orochi.\n\nSign up here: {invite_link}"
                        ),
                        from_email=None,
                        recipient_list=[email],
                        fail_silently=True,
                    )
                except Exception:
                    pass
                messages.success(request, f"Invited {email}. Link: {invite_link}")
            else:
                messages.error(request, f"{email} is already invited.")
