"""CRUD endpoints for AgentGroup (user-defined @mention groups, todo#428)."""

from hub.views.api._common import (
    JsonResponse,
    csrf_exempt,
    get_workspace,
    json,
    login_required,
    require_http_methods,
)


@login_required
@require_http_methods(["GET"])
def api_agent_groups_list(request):
    """GET /api/agent-groups/ — list all groups in the workspace."""
    workspace = get_workspace(request)
    from hub.models import AgentGroup

    groups = AgentGroup.objects.filter(workspace=workspace).prefetch_related("members")
    data = [
        {
            "id": g.id,
            "name": g.name,
            "display_name": g.display_name or g.name,
            "description": g.description,
            "is_builtin": g.is_builtin,
            "member_count": g.members.count(),
            "members": list(g.members.values_list("username", flat=True)),
            "owner": g.owner.username if g.owner else None,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        }
        for g in groups
    ]
    return JsonResponse(data, safe=False)


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_agent_groups_create(request):
    """POST /api/agent-groups/ — create a custom group.

    Body: { "name": str, "display_name": str?, "description": str?,
            "members": [username, …]? }
    """
    workspace = get_workspace(request)
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)

    name = (body.get("name") or "").strip().lower()
    if not name:
        return JsonResponse({"error": "name required"}, status=400)
    if not name.replace("-", "").replace("_", "").isalnum():
        return JsonResponse({"error": "name must be alphanumeric with - or _ only"}, status=400)

    from django.contrib.auth.models import User

    from hub.models import AgentGroup

    if AgentGroup.objects.filter(workspace=workspace, name=name).exists():
        return JsonResponse({"error": f"group '{name}' already exists"}, status=409)

    group = AgentGroup.objects.create(
        workspace=workspace,
        name=name,
        display_name=(body.get("display_name") or "").strip(),
        description=(body.get("description") or "").strip(),
        is_builtin=False,
        owner=request.user,
    )
    member_names = body.get("members") or []
    if member_names:
        users = User.objects.filter(username__in=member_names)
        group.members.set(users)

    return JsonResponse(
        {
            "id": group.id,
            "name": group.name,
            "display_name": group.display_name or group.name,
            "description": group.description,
            "is_builtin": group.is_builtin,
            "member_count": group.members.count(),
            "members": list(group.members.values_list("username", flat=True)),
        },
        status=201,
    )


@csrf_exempt
@login_required
@require_http_methods(["PATCH", "DELETE"])
def api_agent_group_detail(request, name):
    """PATCH /api/agent-groups/<name>/ — update; DELETE — remove (non-builtin only)."""
    workspace = get_workspace(request)
    from hub.models import AgentGroup

    try:
        group = AgentGroup.objects.get(workspace=workspace, name=name.lower())
    except AgentGroup.DoesNotExist:
        return JsonResponse({"error": "not found"}, status=404)

    if request.method == "DELETE":
        if group.is_builtin:
            return JsonResponse({"error": "builtin groups cannot be deleted"}, status=403)
        if group.owner != request.user and not request.user.is_staff:
            return JsonResponse({"error": "only the owner or staff may delete this group"}, status=403)
        group.delete()
        return JsonResponse({"status": "deleted"})

    # PATCH
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)

    if "display_name" in body:
        group.display_name = (body["display_name"] or "").strip()
    if "description" in body:
        group.description = (body["description"] or "").strip()
    if "members" in body:
        from django.contrib.auth.models import User

        users = User.objects.filter(username__in=(body["members"] or []))
        group.members.set(users)
    group.save()

    return JsonResponse(
        {
            "id": group.id,
            "name": group.name,
            "display_name": group.display_name or group.name,
            "description": group.description,
            "is_builtin": group.is_builtin,
            "member_count": group.members.count(),
            "members": list(group.members.values_list("username", flat=True)),
        }
    )
