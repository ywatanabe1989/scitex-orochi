"""Guest invitation API — POST /api/invitations/ (todo#408 Phase 1).

Admin creates a signed invite token for an email address; the response
includes the invite_url the admin can share. The recipient visits the URL,
signs up or logs in, and is added to the workspace as a member.

Only workspace admins and Django superusers may create invitations.
"""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hub.models import WorkspaceInvitation, WorkspaceMember
from hub.views.api._channels import get_workspace


def _is_workspace_admin(request, workspace):
    """Return True if the requesting user is an admin of the workspace."""
    if request.user.is_superuser:
        return True
    return WorkspaceMember.objects.filter(
        workspace=workspace,
        user=request.user,
        role=WorkspaceMember.Role.ADMIN,
    ).exists()


def _invite_url(request, token):
    """Build the absolute invite URL for a given token."""
    scheme = "https" if request.is_secure() else "http"
    host = request.get_host()
    return f"{scheme}://{host}/invite/{token}/"


@csrf_exempt
@require_http_methods(["POST", "GET"])
def api_invitations(request):
    """POST /api/invitations/ — create a workspace invitation link.

    GET  /api/invitations/ — list pending invitations (admin only).

    POST body (JSON): {"email": "user@example.com"}

    Returns 201 with {"token", "invite_url", "email"} on success.
    Returns 400 for missing email, 403 for non-admin, 409 for duplicate.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"error": "auth required"}, status=401)

    workspace = get_workspace(request)
    if workspace is None:
        return JsonResponse({"error": "workspace not found"}, status=404)

    if not _is_workspace_admin(request, workspace):
        return JsonResponse(
            {"error": "only workspace admins can create invitations"}, status=403
        )

    if request.method == "GET":
        invites = WorkspaceInvitation.objects.filter(
            workspace=workspace, accepted=False
        ).order_by("-created_at")
        return JsonResponse(
            {
                "invitations": [
                    {
                        "id": inv.id,
                        "email": inv.email,
                        "token": inv.token,
                        "invite_url": _invite_url(request, inv.token),
                        "created_at": inv.created_at.isoformat(),
                    }
                    for inv in invites
                ]
            }
        )

    # POST — create invitation
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)

    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return JsonResponse({"error": "valid email required"}, status=400)

    # Prevent duplicate pending invites for the same email+workspace combo
    existing = WorkspaceInvitation.objects.filter(
        workspace=workspace, email=email, accepted=False
    ).first()
    if existing:
        return JsonResponse(
            {
                "token": existing.token,
                "invite_url": _invite_url(request, existing.token),
                "email": email,
                "status": "existing",
            },
            status=200,
        )

    invite = WorkspaceInvitation.objects.create(
        workspace=workspace,
        email=email,
        invited_by=request.user,
    )
    return JsonResponse(
        {
            "token": invite.token,
            "invite_url": _invite_url(request, invite.token),
            "email": email,
            "status": "created",
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(["DELETE"])
def api_invitation_detail(request, token):
    """DELETE /api/invitations/<token>/ — revoke a pending invitation."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "auth required"}, status=401)

    workspace = get_workspace(request)
    if workspace is None:
        return JsonResponse({"error": "workspace not found"}, status=404)

    if not _is_workspace_admin(request, workspace):
        return JsonResponse(
            {"error": "only workspace admins can revoke invitations"}, status=403
        )

    deleted, _ = WorkspaceInvitation.objects.filter(
        workspace=workspace, token=token, accepted=False
    ).delete()
    if not deleted:
        return JsonResponse({"error": "invitation not found"}, status=404)
    return JsonResponse({"status": "revoked"})
