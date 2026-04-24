"""Admin-scoped agent channel subscription endpoints (issue #262 §9.1).

These views let a fleet-coordinator (workspace ``admin`` or ``staff``
role) toggle another agent's persistent ``ChannelMembership`` rows
without that agent having to be online. The MCP ``subscribe`` /
``unsubscribe`` tools route here when called with the optional
``target_agent`` argument; the existing self-targeting WS path stays
untouched.

The view body is intentionally small — most of the work is delegated to
:func:`hub.consumers._helpers._persist_agent_subscription` so the WS
path and the admin REST path share a single ``ChannelMembership``
mutation surface (no risk of the two diverging).
"""

import re

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from hub.consumers._helpers import _persist_agent_subscription
from hub.models import normalize_channel_name
from hub.views._helpers import resolve_workspace_and_actor
from hub.views.api._common import (
    JsonResponse,
    csrf_exempt,
    json,
    log,
    require_http_methods,
)

_ADMIN_ROLES = {"admin", "staff"}


def _admin_subscribe(request, target, *, slug=None, subscribe: bool):
    """Shared body for the admin subscribe + unsubscribe endpoints."""
    workspace, actor, err = resolve_workspace_and_actor(request, slug=slug)
    if err is not None:
        return err

    actor_role = (getattr(actor, "role", "") or "").lower()
    if actor_role not in _ADMIN_ROLES:
        return JsonResponse(
            {
                "error": {
                    "code": "permission_denied",
                    "reason": "agent-scope tokens cannot manage other agents",
                    "hint": "Run as admin or use the dashboard",
                }
            },
            status=403,
        )

    target_name = (target or "").strip()
    if not target_name or not re.match(r"^[a-zA-Z0-9_.\-]+$", target_name):
        return JsonResponse(
            {
                "error": {
                    "code": "invalid_input",
                    "reason": "target agent name missing or malformed",
                    "hint": "pass a non-empty name matching [a-zA-Z0-9_.-]+",
                }
            },
            status=400,
        )

    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse(
                {
                    "error": {
                        "code": "invalid_input",
                        "reason": "request body is not valid JSON",
                        "hint": "POST a JSON object with {\"channel\": \"#name\"}",
                    }
                },
                status=400,
            )

    raw_channel = (body.get("channel") or "").strip()
    if not raw_channel:
        return JsonResponse(
            {
                "error": {
                    "code": "invalid_input",
                    "reason": "channel is required",
                    "hint": "include a non-empty channel name in the request body",
                }
            },
            status=400,
        )

    ch_name = normalize_channel_name(raw_channel)

    # msg#16884 bit-split: admin callers may pass ``can_read`` /
    # ``can_write`` booleans to install a write-only / read-only row
    # instead of the default read-write. Omitted = True = pre-split
    # behaviour, so existing admin scripts keep working untouched.
    can_read = bool(body.get("can_read", True))
    can_write = bool(body.get("can_write", True))

    # ``_persist_agent_subscription`` is an async helper; wrap it so the
    # synchronous view can call it without spinning a loop. It returns
    # ``False`` only when the workspace cannot be resolved — every other
    # failure raises.
    ok = async_to_sync(_persist_agent_subscription)(
        workspace.id,
        target_name,
        ch_name,
        subscribe,
        can_read=can_read,
        can_write=can_write,
    )
    if not ok:
        return JsonResponse(
            {
                "error": {
                    "code": "internal_error",
                    "reason": "could not persist subscription",
                    "hint": "check the hub log for the underlying error",
                }
            },
            status=500,
        )

    # If the target is currently connected, nudge its consumer so the
    # in-memory channel-layer group membership picks up the change without
    # waiting for a reconnect. The consumer listens on its per-agent group
    # for ``agent.subscribe.refresh`` and rehydrates from the DB.
    try:
        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(
                f"agent_{workspace.id}_{target_name}",
                {
                    "type": "agent.subscribe.refresh",
                    "channel": ch_name,
                    "subscribe": bool(subscribe),
                },
            )
    except Exception as exc:  # pragma: no cover — best-effort nudge
        log.debug(
            "admin subscribe nudge failed for %s/%s: %s",
            target_name,
            ch_name,
            exc,
        )

    log.info(
        "admin %s: %s %s on %s by %s",
        "subscribe" if subscribe else "unsubscribe",
        target_name,
        ch_name,
        workspace.name,
        getattr(actor.user, "username", "?"),
    )

    return JsonResponse(
        {
            "status": "ok",
            "target_agent": target_name,
            "channel": ch_name,
            "action": "subscribe" if subscribe else "unsubscribe",
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_agent_subscribe(request, target, slug=None):
    """``POST /api/agents/<target>/subscribe/`` — admin subscribe a peer.

    Body: ``{"channel": "#name"}``. Auth: workspace token + ``?agent=``
    or Django session — but the actor must hold the ``admin`` (or
    ``staff``) role on the resolved workspace.
    """
    return _admin_subscribe(request, target, slug=slug, subscribe=True)


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_agent_unsubscribe(request, target, slug=None):
    """``POST /api/agents/<target>/unsubscribe/`` — admin unsubscribe a peer."""
    return _admin_subscribe(request, target, slug=slug, subscribe=False)
