"""Helpers shared between the SDK executor and the WS reply callback.

Extracted from the old ``hub/views/api/_a2a_dispatch.py`` Django view
when Phase 3 deleted the non-spec ``/api/a2a/dispatch/<slug>/<agent>/``
route. The reply-correlation map (``_PENDING``) and the dispatch
helpers stay here because:

* :class:`hub.a2a.executor.OrochiAgentExecutor` uses them to issue the
  same Tier-3 HTTP-direct → WS-fallback dispatch the old view did.
* :func:`hub.views.api._a2a_dispatch.api_a2a_reply` (the only Django
  view left in that module) sets entries in ``_PENDING`` when an agent
  POSTs back its reply through the WS bridge.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from channels.db import database_sync_to_async

log = logging.getLogger("orochi.a2a")

# In-process reply correlation. The SDK executor (or — historically —
# the deleted ``api_a2a_dispatch`` view) creates an entry per dispatch
# and awaits its ``asyncio.Event``; ``api_a2a_reply`` (kept) sets it
# when the agent's WS bridge POSTs back. Single-process daphne only;
# horizontal scaling would move this to Redis pub/sub.
_PENDING: dict[str, dict[str, Any]] = {}

DISPATCH_TIMEOUT_SECONDS = 30.0
HTTP_DIRECT_TIMEOUT_SECONDS = 25.0


def _try_http_direct(
    a2a_url: str, body: dict[str, Any]
) -> tuple[bool, dict | None]:
    """Try HTTP POST to the agent's a2a_url. Return (ok, parsed_response)."""
    try:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            a2a_url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(
            req, timeout=HTTP_DIRECT_TIMEOUT_SECONDS
        ) as resp:
            return True, json.loads(resp.read())
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        OSError,
        ValueError,
    ) as exc:
        log.info(
            "a2a HTTP-direct to %s failed: %s — falling back to WS",
            a2a_url,
            exc,
        )
        return False, None


def _agent_group(workspace_id: int, agent: str) -> str:
    """Match the per-agent group name used by ``AgentConsumer``."""
    return f"agent_{workspace_id}_{agent}"


@database_sync_to_async
def _resolve_workspace_id(slug_or_id: str) -> int | None:
    """Resolve a workspace name or numeric id to its DB id.

    The Workspace orochi_model has no ``slug`` field — historic URLs used
    ``slug`` for parity with other ``api/workspace/<slug:slug>/...``
    routes, but the DB lookup is by ``name``.
    """
    from hub.models import Workspace

    if slug_or_id.isdigit():
        ws = Workspace.objects.filter(id=int(slug_or_id)).first()
    else:
        ws = Workspace.objects.filter(name=slug_or_id).first()
    return ws.id if ws else None
