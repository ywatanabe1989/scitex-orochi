"""WS-bridge reply callback for the orochi A2A surface.

After Phase 3 of ``GITIGNORED/A2A_MIGRATION.md`` the canonical
``/v1/agents/<name>/`` URL is served by the official a2a-sdk Starlette
app (see :mod:`hub.a2a.mount`); the old non-spec
``/api/a2a/dispatch/<slug>/<agent>/`` Django view was deleted in the
same change. The dispatch helpers (``_PENDING``, ``_try_http_direct``,
``_agent_group``, ``_resolve_workspace_id``) moved to
:mod:`hub.a2a._dispatch_internals` so :class:`hub.a2a.executor.OrochiAgentExecutor`
can reuse them.

The only Django view left here is :func:`api_a2a_reply` — the agent's
WS bridge POSTs back to ``/api/a2a/reply/`` with its JSON-RPC reply,
which the executor's ``asyncio.Event`` waiter unblocks. Keeping this
URL Django-served avoids retraining every fleet agent at the same
time as the SDK surface lands.
"""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

# Re-export the dispatch helpers from their new home so any code that
# still imports them from ``hub.views.api._a2a_dispatch`` keeps working
# during the migration. Once the in-tree consumers are updated this
# re-export can be removed.
from hub.a2a._dispatch_internals import (  # noqa: F401
    _PENDING,
    DISPATCH_TIMEOUT_SECONDS,
    HTTP_DIRECT_TIMEOUT_SECONDS,
    _agent_group,
    _resolve_workspace_id,
    _try_http_direct,
    log,
)


@csrf_exempt
@require_POST
async def api_a2a_reply(request):
    """Agent-side callback: deliver an A2A reply by ``reply_id``.

    Body: ``{"reply_id": "...", "result": {...JSON-RPC body...}}``.
    The matching :class:`hub.a2a.executor.OrochiAgentExecutor` waiter
    unblocks and returns the ``result`` to the SDK ``event_queue``.

    Async to share the event loop with the dispatch waiter — setting a
    plain ``asyncio.Event`` only wakes coroutines on the same loop.
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


__all__ = ["api_a2a_reply"]
