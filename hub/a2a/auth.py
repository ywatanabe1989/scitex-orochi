"""WorkspaceToken auth wiring for the SDK request handler.

The pre-flight noted that orochi has no central auth middleware — every
existing API view inlines ``WorkspaceToken.objects.get(token=...)``.
For Phase 3 we factor that pattern into one helper here and plug it
into the SDK's :class:`ServerCallContextBuilder`, so the executor can
reject unauthenticated requests with a proper JSON-RPC error and know
which workspace the caller belongs to.

Bearer-token resolution priority (matching ``_auto_dispatch.py``):
1. ``Authorization: Bearer wks_...`` header
2. ``?token=wks_...`` query string
3. JSON body ``{"token": "wks_..."}`` — checked by the executor, not
   here, because the request body is consumed by the dispatcher.
"""

from __future__ import annotations

from typing import Any

from a2a.auth.user import UnauthenticatedUser, User
from a2a.server.context import ServerCallContext
from a2a.server.routes.common import ServerCallContextBuilder


class _WorkspaceUser(User):
    """SDK ``User`` adapter wrapping a resolved :class:`Workspace`."""

    def __init__(self, workspace: Any, token_str: str):
        self._workspace = workspace
        self._token = token_str

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        return f"workspace:{getattr(self._workspace, 'name', '?')}"


def _extract_bearer(headers: Any) -> str | None:
    """Pull a ``wks_*`` token from an ``Authorization: Bearer`` header."""
    auth = ""
    try:
        auth = headers.get("authorization", "") or ""
    except AttributeError:
        # Fallback for case-sensitive raw header lists.
        try:
            for k, v in headers:
                kk = k.decode() if isinstance(k, bytes) else k
                if kk.lower() == "authorization":
                    auth = v.decode() if isinstance(v, bytes) else v
                    break
        except Exception:
            return None
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _lookup_token_sync(token: str) -> Any | None:
    from hub.models import WorkspaceToken

    try:
        row = WorkspaceToken.objects.select_related("workspace").get(token=token)
    except WorkspaceToken.DoesNotExist:
        return None
    return row.workspace


def resolve_workspace_token(request: Any) -> tuple[Any | None, str | None]:
    """Resolve the calling workspace from a Starlette request.

    Returns ``(workspace, token_str)`` on success, ``(None, None)`` if
    no token was supplied or the lookup failed. Detects the async
    context (the SDK calls us from inside an event loop) and dispatches
    the ORM read through ``database_sync_to_async`` accordingly.
    """
    token = _extract_bearer(request.headers) or request.query_params.get("token")
    if not token:
        return None, None
    # ``ServerCallContextBuilder.build`` is sync but called from inside
    # the SDK's async dispatcher. Run the ORM read on a worker thread
    # so Django's ``async_unsafe`` guard doesn't fire.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        workspace = ex.submit(_lookup_token_sync, token).result()
    if workspace is None:
        return None, None
    return workspace, token


class WorkspaceTokenContextBuilder(ServerCallContextBuilder):
    """SDK context builder that requires a ``WorkspaceToken``.

    Stashes the resolved :class:`Workspace` in
    ``ServerCallContext.state["workspace"]`` and the raw token under
    ``state["workspace_token"]`` so :class:`OrochiAgentExecutor` can
    reuse them. When no valid token is present, the returned context
    carries an :class:`UnauthenticatedUser` and ``state["workspace"]``
    is ``None`` — the executor checks this and emits a JSON-RPC
    -32001 error before doing any dispatch work.
    """

    def build(self, request: Any) -> ServerCallContext:
        workspace, token_str = resolve_workspace_token(request)
        state: dict[str, Any] = {
            "headers": dict(request.headers),
            "workspace": workspace,
            "workspace_token": token_str,
        }
        # Capture the per-request agent name from the URL path params
        # — Starlette puts ``Mount("/v1/agents/{name}", ...)`` matches
        # in ``request.path_params``. The executor reads this to know
        # which agent the dispatch targets.
        try:
            state["agent_name"] = request.path_params.get("name")
        except Exception:
            state["agent_name"] = None

        user: User = (
            _WorkspaceUser(workspace, token_str or "")
            if workspace is not None
            else UnauthenticatedUser()
        )
        return ServerCallContext(state=state, user=user)


__all__ = [
    "WorkspaceTokenContextBuilder",
    "resolve_workspace_token",
]
