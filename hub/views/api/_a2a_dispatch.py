"""A2A protocol dispatch bridge — NAS Django → orochi hub → live agent.

Wires the canonical A2A capability surface at ``a2a.scitex.ai`` into
the running fleet of agents on the orochi hub:

* :func:`api_a2a_dispatch` — POST entry: NAS Django proxies inbound
  A2A JSON-RPC here; the hub fans out to the target agent's WebSocket
  consumer via the per-agent Channels group, then blocks until either
  the agent posts a reply or the timeout fires.
* :func:`api_a2a_reply` — POST callback: the agent's MCP side calls
  this to deliver the reply, which unblocks the dispatch waiter.

Reply correlation uses an in-process ``asyncio.Event`` map keyed by a
random ``reply_id``. This works because the hub today is a single
process; if it ever scales horizontally, the map moves to Redis pub/sub.

For Tier 3 mock (mock-echo) the agent is a tiny Python WS client that
joins ``agent_<ws_id>_mock-echo`` and replies on receipt. The same code
path serves real Claude Code agents once they grow an A2A-dispatch
handler in their MCP channel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

log = logging.getLogger("orochi.a2a")

# In-process reply correlation. Each entry is set by api_a2a_reply
# and awaited by api_a2a_dispatch. Cleared in the dispatch view's
# finally block to avoid leaks.
_PENDING: dict[str, dict[str, Any]] = {}

DISPATCH_TIMEOUT_SECONDS = 30.0


def _agent_group(workspace_id: int, agent: str) -> str:
    """Match the per-agent group name used by ``AgentConsumer``."""
    return f"agent_{workspace_id}_{agent}"


def _resolve_workspace_id(slug_or_id: str) -> int | None:
    """Resolve a workspace name or numeric id to its DB id.

    The Workspace model has no ``slug`` field — the URL kwarg is named
    ``slug`` for parity with other ``api/workspace/<slug:slug>/...``
    routes, but the DB lookup is by ``name``.
    """
    from hub.models import Workspace

    if slug_or_id.isdigit():
        ws = Workspace.objects.filter(id=int(slug_or_id)).first()
    else:
        ws = Workspace.objects.filter(name=slug_or_id).first()
    return ws.id if ws else None


@csrf_exempt
@require_POST
def api_a2a_dispatch(request, slug: str, agent: str):
    """Forward an A2A JSON-RPC body to ``agent`` on workspace ``slug``.

    Body: the raw A2A JSON-RPC envelope (``{jsonrpc, id, method, params}``).
    Returns: the agent's JSON-RPC reply, or 504 on timeout, or 404 if
    the agent is not currently connected.
    """
    ws_id = _resolve_workspace_id(slug)
    if ws_id is None:
        return JsonResponse({"error": f"workspace not found: {slug}"}, status=404)

    try:
        body = json.loads(request.body.decode() or "{}")
    except (json.JSONDecodeError, ValueError) as exc:
        return JsonResponse({"error": f"bad JSON: {exc}"}, status=400)

    reply_id = secrets.token_urlsafe(16)
    event = asyncio.Event()
    _PENDING[reply_id] = {"event": event, "value": None, "ts": time.time()}

    layer = get_channel_layer()
    if layer is None:
        del _PENDING[reply_id]
        return JsonResponse({"error": "no channel layer"}, status=503)

    group = _agent_group(ws_id, agent)
    try:
        async_to_sync(layer.group_send)(
            group,
            {
                "type": "a2a.dispatch",
                "reply_id": reply_id,
                "body": body,
            },
        )
    except Exception as exc:  # noqa: BLE001
        del _PENDING[reply_id]
        log.exception("a2a dispatch group_send failed: %s", exc)
        return JsonResponse({"error": f"dispatch failed: {exc}"}, status=502)

    async def _await_reply() -> dict[str, Any] | None:
        try:
            await asyncio.wait_for(event.wait(), timeout=DISPATCH_TIMEOUT_SECONDS)
            return _PENDING[reply_id]["value"]
        except asyncio.TimeoutError:
            return None

    try:
        result = async_to_sync(_await_reply)()
    finally:
        _PENDING.pop(reply_id, None)

    if result is None:
        return JsonResponse(
            {
                "error": (
                    f"timeout waiting {DISPATCH_TIMEOUT_SECONDS:.0f}s "
                    f"for reply from agent {agent!r}"
                ),
            },
            status=504,
        )

    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})


@csrf_exempt
@require_POST
def api_a2a_reply(request):
    """Agent-side callback: deliver an A2A reply by ``reply_id``.

    Body: ``{"reply_id": "...", "result": {...JSON-RPC body...}}``.
    The matching :func:`api_a2a_dispatch` waiter unblocks and returns
    the ``result`` to its caller.
    """
    try:
        body = json.loads(request.body.decode() or "{}")
    except (json.JSONDecodeError, ValueError) as exc:
        return JsonResponse({"error": f"bad JSON: {exc}"}, status=400)

    reply_id = body.get("reply_id")
    result = body.get("result")
    if not reply_id or result is None:
        return JsonResponse({"error": "reply_id and result required"}, status=400)

    pending = _PENDING.get(reply_id)
    if pending is None:
        return JsonResponse({"error": "reply_id unknown or expired"}, status=410)

    pending["value"] = result
    pending["event"].set()
    return JsonResponse({"ok": True, "reply_id": reply_id})
