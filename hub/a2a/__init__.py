"""A2A SDK integration — orochi serves the canonical A2A surface.

Phase 3 of ``GITIGNORED/A2A_MIGRATION.md``. Mounts the official a2a-sdk
Starlette routes under ``/v1/agents/<name>/`` and dispatches into the
live fleet via the existing Tier-3 (HTTP-direct) / WebSocket fallback
path. The non-spec ``/api/a2a/dispatch/<slug>/<agent>/`` URL is removed
in the same release; only the WS reply callback (``api_a2a_reply``)
remains, since agents still POST replies through the Channels bridge.

Modules
-------
- :mod:`._dispatch_internals` — reply-correlation map (``_PENDING``),
  HTTP-direct + Channels group_send helpers reused by both the SDK
  executor and the WS reply callback.
- :mod:`.executor` — :class:`OrochiAgentExecutor` (SDK ``AgentExecutor``).
- :mod:`.card` — AgentCard projection from registry / DB metadata.
- :mod:`.auth` — :class:`WorkspaceTokenContextBuilder` resolves the
  caller's :class:`hub.models.WorkspaceToken` and rejects unauth calls.
- :mod:`.mount` — builds the Starlette sub-app with a single
  ``Mount("/v1/agents/{name}", ...)`` and lazy per-agent card resolution.
"""

from hub.a2a._dispatch_internals import (
    DISPATCH_TIMEOUT_SECONDS,
    HTTP_DIRECT_TIMEOUT_SECONDS,
    _PENDING,
    _agent_group,
    _resolve_workspace_id,
    _try_http_direct,
)

__all__ = [
    "DISPATCH_TIMEOUT_SECONDS",
    "HTTP_DIRECT_TIMEOUT_SECONDS",
    "_PENDING",
    "_agent_group",
    "_resolve_workspace_id",
    "_try_http_direct",
]
