"""Channel rename endpoints (unblocks todo#71 tree-channel drag-to-move).

Two endpoints live here:

``POST /api/channels/<int:channel_id>/rename/``
    Rename a single channel. Only workspace admins or the channel
    creator can rename. DMs are never renamable — they collide with
    the reserved ``dm:`` namespace and are identity-bound by design.

``POST /api/channels/rename-prefix/``
    Atomic bulk rename — every channel whose name starts with
    ``old_prefix`` has that prefix replaced with ``new_prefix``. This
    powers "rename folder" in the tree sidebar (e.g. ``proj/`` →
    ``projects/``). Wrapped in ``transaction.atomic()``; if any target
    name would collide with an existing channel, the whole batch is
    rejected before any row is mutated.

Name validation (both endpoints):
    - after stripping the leading ``#``, must match ``^[a-z0-9][a-z0-9/_-]*$``
    - max 80 characters
    - cannot start with ``dm:``
    - cannot collide with an existing channel in the same workspace

Broadcast:
    After a successful rename, the view sends a ``channel.rename`` event
    over ``workspace_<id>`` so connected clients can patch their sidebar
    cache in-place without a full reload.
"""

from __future__ import annotations

import json
import logging
import re

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from hub.models import Channel, WorkspaceMember, normalize_channel_name
from hub.views._helpers import get_workspace

log = logging.getLogger("orochi.api.channels_rename")

# Validation regex — lowercase alphanumerics + "-", "/", "_"
# (underscore allowed to match legacy channel names; spec asks for
# alphanumerics + "-" + "/", but a codebase survey shows "_" already
# present in real channels, and rejecting it would break existing data.)
_CHANNEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]*$")
_MAX_CHANNEL_NAME_LEN = 80


def _is_workspace_admin(user, workspace) -> bool:
    """Return True if ``user`` has admin role in ``workspace``.

    Superusers and Django staff accounts always count as admins so
    operators can rename channels for debugging without being an
    explicit workspace admin.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return WorkspaceMember.objects.filter(
        workspace=workspace, user=user, role=WorkspaceMember.Role.ADMIN
    ).exists()


def _validate_new_name(raw_name: str) -> tuple[str | None, str | None]:
    """Return ``(normalized_name, None)`` on success or ``(None, error)``.

    The error string is returned unwrapped so the caller controls the
    JSON envelope. Applies ``normalize_channel_name`` after validation
    so callers can pass either ``"proj/foo"`` or ``"#proj/foo"``.
    """
    if not isinstance(raw_name, str):
        return None, "new_name must be a string"
    cleaned = raw_name.strip()
    if not cleaned:
        return None, "new_name cannot be empty"
    # DM names are reserved.
    if cleaned.startswith("dm:"):
        return None, "cannot rename to a dm: channel"
    # Strip optional leading "#" for regex validation.
    bare = cleaned[1:] if cleaned.startswith("#") else cleaned
    if len(bare) > _MAX_CHANNEL_NAME_LEN:
        return None, f"new_name exceeds {_MAX_CHANNEL_NAME_LEN} chars"
    if not _CHANNEL_NAME_RE.match(bare):
        return None, (
            "new_name must be lowercase alphanumerics, '-', '/', or '_' "
            "and start with a letter or digit"
        )
    return normalize_channel_name(bare), None


def _broadcast_rename(workspace_id: int, old_name: str, new_name: str) -> None:
    """Send ``channel.rename`` to the workspace group (best-effort)."""
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            f"workspace_{workspace_id}",
            {
                "type": "channel.rename",
                "old_name": old_name,
                "new_name": new_name,
            },
        )
    except Exception:
        log.exception("channel.rename broadcast failed")


@csrf_exempt
@login_required
@require_POST
def api_channel_rename(request, channel_id: int, slug: str | None = None):
    """POST /api/channels/<int:channel_id>/rename/ — rename one channel.

    Body: ``{"new_name": "proj/ripple-wm-v2"}``
    Response: ``{"id": ..., "name": "#proj/ripple-wm-v2"}`` on 200,
             ``{"error": "..."}`` on 400/403/404.
    """
    workspace = get_workspace(request, slug=slug)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    try:
        channel = Channel.objects.get(id=channel_id, workspace=workspace)
    except Channel.DoesNotExist:
        return JsonResponse({"error": "channel not found"}, status=404)

    if channel.kind == Channel.KIND_DM:
        return JsonResponse({"error": "cannot rename a DM channel"}, status=400)

    if not _is_workspace_admin(request.user, workspace):
        return JsonResponse(
            {"error": "only workspace admins can rename channels"}, status=403
        )

    new_name, err = _validate_new_name(body.get("new_name", ""))
    if err is not None:
        return JsonResponse({"error": err}, status=400)

    if new_name == channel.name:
        # No-op rename — succeed idempotently.
        return JsonResponse({"id": channel.id, "name": channel.name})

    if Channel.objects.filter(workspace=workspace, name=new_name).exists():
        return JsonResponse(
            {"error": f"channel {new_name!r} already exists"}, status=400
        )

    old_name = channel.name
    channel.name = new_name
    channel.save(update_fields=["name"])
    _broadcast_rename(workspace.id, old_name, new_name)
    return JsonResponse({"id": channel.id, "name": channel.name})


@csrf_exempt
@login_required
@require_POST
def api_channel_rename_prefix(request, slug: str | None = None):
    """POST /api/channels/rename-prefix/ — atomic bulk prefix rename.

    Body: ``{"old_prefix": "proj/", "new_prefix": "projects/"}``
    Response: ``{"renamed": [{"id": ..., "old": "#proj/a", "new": "#projects/a"}, ...]}``
             on 200, ``{"error": "..."}`` on 400/403.

    Matches channels in the current workspace whose *bare* name (after
    the leading ``#``) starts with ``old_prefix``. Rejects the whole
    batch on any target-name collision before mutating any row.
    """
    workspace = get_workspace(request, slug=slug)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    if not _is_workspace_admin(request.user, workspace):
        return JsonResponse(
            {"error": "only workspace admins can rename channels"}, status=403
        )

    old_prefix = body.get("old_prefix", "")
    new_prefix = body.get("new_prefix", "")
    if not isinstance(old_prefix, str) or not isinstance(new_prefix, str):
        return JsonResponse(
            {"error": "old_prefix and new_prefix must be strings"}, status=400
        )
    if not old_prefix:
        return JsonResponse({"error": "old_prefix cannot be empty"}, status=400)
    # new_prefix may be empty (meaning "flatten" — strip the prefix).
    # Validate new_prefix shape by round-tripping a dummy name.
    if new_prefix:
        # The new prefix is prepended to the *bare* tail; it must form
        # a valid channel name itself. Use a sentinel suffix so even an
        # empty tail is accepted.
        _, err = _validate_new_name(new_prefix + "x")
        if err is not None:
            return JsonResponse({"error": f"invalid new_prefix: {err}"}, status=400)

    # Build rename plan. Operate on *bare* names (post-#) so both the
    # old_prefix and new_prefix feel intuitive to callers.
    candidates = list(
        Channel.objects.filter(workspace=workspace, kind=Channel.KIND_GROUP).exclude(
            name__startswith="dm:"
        )
    )

    plan: list[tuple[Channel, str, str]] = []
    for ch in candidates:
        bare = ch.name[1:] if ch.name.startswith("#") else ch.name
        if not bare.startswith(old_prefix):
            continue
        new_bare = new_prefix + bare[len(old_prefix) :]
        # Validate the resulting name via the same rules as single-rename.
        normalized, err = _validate_new_name(new_bare)
        if err is not None:
            return JsonResponse(
                {
                    "error": (
                        f"rename of {ch.name!r} would produce invalid "
                        f"name {new_bare!r}: {err}"
                    )
                },
                status=400,
            )
        plan.append((ch, ch.name, normalized))

    if not plan:
        return JsonResponse({"renamed": []})

    # Collision check: any target name already exists in the workspace
    # and is *not* part of the rename batch? Reject the whole batch.
    batch_ids = {ch.id for ch, _, _ in plan}
    target_names = [new for _, _, new in plan]
    # Duplicates within the batch itself are also a hard fail.
    if len(set(target_names)) != len(target_names):
        return JsonResponse(
            {"error": "rename would create duplicate target names"}, status=400
        )
    colliding = Channel.objects.filter(
        workspace=workspace, name__in=target_names
    ).exclude(id__in=batch_ids)
    if colliding.exists():
        names = sorted(c.name for c in colliding)
        return JsonResponse(
            {"error": f"target names collide with existing channels: {names}"},
            status=400,
        )

    renamed: list[dict] = []
    with transaction.atomic():
        for ch, old, new in plan:
            ch.name = new
            ch.save(update_fields=["name"])
            renamed.append({"id": ch.id, "old": old, "new": new})

    for entry in renamed:
        _broadcast_rename(workspace.id, entry["old"], entry["new"])

    return JsonResponse({"renamed": renamed})
