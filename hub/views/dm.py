"""Direct-message (DM) channel REST API.

Implements the ``#dm-{lo}__{hi}`` DM channel scheme. DM channels reuse
the existing ``Channel`` + ``Message`` storage; access control lives
entirely in the channel name — the hub canonicalizes on every write so
a client cannot impersonate a DM it is not a participant in.

Endpoints:
- ``POST /api/dm/send/``           send a DM (create-or-get channel)
- ``GET  /api/dm/list/``           list DMs the caller participates in
- ``GET  /api/dm/<channel>/history/`` paginated history of one DM

Auth: session (browser) OR workspace token (agent). When authenticated
via token the caller MUST pass ``sender`` in the POST body / query
string so the hub knows which principal is acting; when session-authed
the Django username is used.
"""

import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from hub.models import (
    Channel,
    Message,
    Workspace,
    WorkspaceToken,
    canonical_dm_name,
    dm_includes,
    dm_participants_from_name,
    DM_PREFIX,
)
from hub.views._helpers import get_workspace

log = logging.getLogger("orochi.api.dm")


# ---------------------------------------------------------------------------
# auth helper
# ---------------------------------------------------------------------------

def _resolve_principal(request, body=None):
    """Return ``(workspace, principal, error_response_or_None)``.

    Session auth uses ``request.user.username`` as the principal and
    the subdomain-resolved workspace.  Token auth requires an explicit
    ``sender`` field so multiple agents can share a workspace token
    without confusing their identities on the hub side.
    """
    body = body or {}
    token_str = (
        body.get("token")
        or request.GET.get("token")
        or request.POST.get("token")
    )
    if token_str:
        try:
            wt = WorkspaceToken.objects.select_related("workspace").get(
                token=token_str
            )
        except WorkspaceToken.DoesNotExist:
            return None, None, JsonResponse({"error": "invalid token"}, status=401)
        workspace = wt.workspace
        principal = (
            body.get("sender")
            or request.GET.get("sender")
            or request.POST.get("sender")
            or ""
        ).strip()
        if not principal:
            return None, None, JsonResponse(
                {"error": "sender required when using workspace token"},
                status=400,
            )
        return workspace, principal, None

    if not (request.user and request.user.is_authenticated):
        return None, None, JsonResponse({"error": "auth required"}, status=401)
    try:
        workspace = get_workspace(request)
    except Exception:
        return None, None, JsonResponse(
            {"error": "workspace not resolved"}, status=400
        )
    return workspace, request.user.username, None


# ---------------------------------------------------------------------------
# POST /api/dm/send/
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def api_dm_send(request):
    """Send a direct message.

    Body JSON: ``{recipient, text, [sender], [token], [metadata]}``.
    Returns ``{ok, channel, message_id, ts}``.
    """
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)

    workspace, principal, err = _resolve_principal(request, body)
    if err:
        return err

    recipient = (body.get("recipient") or "").strip()
    text = body.get("text") or body.get("content") or ""
    metadata = body.get("metadata") or {}
    if not recipient:
        return JsonResponse({"error": "recipient required"}, status=400)
    if not text:
        return JsonResponse({"error": "text required"}, status=400)

    try:
        ch_name = canonical_dm_name(principal, recipient)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    channel, _created = Channel.objects.get_or_create(
        workspace=workspace,
        name=ch_name,
        defaults={"kind": Channel.KIND_DM, "description": "direct message"},
    )
    # Upgrade kind in case the row was created as public somehow
    # (defensive — hub is the only writer of DM names so this shouldn't
    # happen, but cheap to enforce).
    if channel.kind != Channel.KIND_DM:
        channel.kind = Channel.KIND_DM
        channel.save(update_fields=["kind"])

    msg = Message.objects.create(
        workspace=workspace,
        channel=channel,
        sender=principal,
        sender_type="agent" if body.get("token") else "human",
        content=text,
        metadata=metadata,
    )

    # Broadcast to per-principal DM groups — one group per participant
    # so each side's connected sockets receive the event without having
    # to subscribe to the channel name explicitly.
    layer = get_channel_layer()
    participants = dm_participants_from_name(ch_name)
    event = {
        "type": "dm.message",
        "id": msg.id,
        "channel": ch_name,
        "sender": principal,
        "sender_type": msg.sender_type,
        "text": text,
        "ts": msg.ts.isoformat(),
        "metadata": metadata,
    }
    for p in participants:
        group = _dm_principal_group(workspace.id, p)
        async_to_sync(layer.group_send)(group, event)

    return JsonResponse(
        {
            "ok": True,
            "channel": ch_name,
            "message_id": msg.id,
            "ts": msg.ts.isoformat(),
        },
        status=201,
    )


# ---------------------------------------------------------------------------
# GET /api/dm/list/
# ---------------------------------------------------------------------------

@require_GET
def api_dm_list(request):
    """List DM channels the caller participates in, with last-msg preview."""
    workspace, principal, err = _resolve_principal(request)
    if err:
        return err

    p = principal.strip().lstrip("@#").lower()
    # All DM channels in this workspace whose canonical name contains the
    # principal. Participant names are separated by ``__`` and surrounded
    # by either the prefix or another ``__``.
    qs = Channel.objects.filter(
        workspace=workspace, kind=Channel.KIND_DM
    ).filter(name__contains=p)

    results = []
    for ch in qs:
        parts = dm_participants_from_name(ch.name)
        if p not in parts:
            continue  # substring match false positive
        peer = next((x for x in parts if x != p), p)  # self-DM peer == self
        last = (
            Message.objects.filter(channel=ch).order_by("-ts").first()
        )
        results.append(
            {
                "channel": ch.name,
                "peer": peer,
                "last_message_at": last.ts.isoformat() if last else None,
                "last_message_preview": (last.content[:120] if last else ""),
                "last_sender": last.sender if last else None,
                "unread": 0,  # TODO: wire up read receipts (todo#60 follow-up)
            }
        )
    results.sort(
        key=lambda r: r["last_message_at"] or "", reverse=True
    )
    return JsonResponse(results, safe=False)


# ---------------------------------------------------------------------------
# GET /api/dm/<channel>/history/
# ---------------------------------------------------------------------------

@require_GET
def api_dm_history(request, channel_name):
    """Return paginated DM history. Requires caller to be a participant."""
    workspace, principal, err = _resolve_principal(request)
    if err:
        return err

    if not channel_name.startswith(DM_PREFIX):
        channel_name = f"{DM_PREFIX}{channel_name.lstrip('#')}"

    if not dm_includes(channel_name, principal):
        return JsonResponse(
            {"error": "forbidden: not a DM participant"}, status=403
        )

    try:
        channel = Channel.objects.get(
            workspace=workspace, name=channel_name, kind=Channel.KIND_DM
        )
    except Channel.DoesNotExist:
        return JsonResponse([], safe=False)

    try:
        limit = min(int(request.GET.get("limit", "50")), 500)
    except (TypeError, ValueError):
        limit = 50
    before = request.GET.get("before")

    qs = Message.objects.filter(channel=channel).order_by("-ts")
    if before:
        qs = qs.filter(ts__lt=before)
    msgs = qs[:limit]
    data = [
        {
            "id": m.id,
            "channel": channel.name,
            "sender": m.sender,
            "sender_type": m.sender_type,
            "content": m.content,
            "ts": m.ts.isoformat(),
            "metadata": m.metadata,
        }
        for m in msgs
    ]
    return JsonResponse(data, safe=False)


# ---------------------------------------------------------------------------
# internal: group name helper (shared with consumers.py)
# ---------------------------------------------------------------------------

def _dm_principal_group(workspace_id: int, principal: str) -> str:
    """Return the channel-layer group name for a principal's DM inbox.

    Must match ``^[a-zA-Z0-9._-]{1,99}$`` per Django Channels.
    """
    import re

    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", principal.lower()).strip("-_.") or "x"
    return f"dm_inbox_{workspace_id}_{safe}"[:99]
