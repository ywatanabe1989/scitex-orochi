"""Orochi authentication -- admin token + workspace token resolution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from scitex_orochi._config import ADMIN_TOKEN

if TYPE_CHECKING:
    from scitex_orochi._workspaces import WorkspaceStore

log = logging.getLogger("orochi.auth")


@dataclass
class AuthResult:
    """Result of token verification."""

    workspace_id: str | None  # None means admin token
    is_admin: bool


async def verify_token(
    token: str | None,
    workspace_store: WorkspaceStore | None = None,
) -> AuthResult | None:
    """Verify a connection token.

    Returns AuthResult on success, None on rejection.
    Checks admin token first, then workspace tokens.
    """
    if not token:
        log.warning("Connection rejected: no token provided")
        return None

    if ADMIN_TOKEN and token == ADMIN_TOKEN:
        return AuthResult(workspace_id=None, is_admin=True)

    if workspace_store:
        ws_id = await workspace_store.resolve_token(token)
        if ws_id:
            return AuthResult(workspace_id=ws_id, is_admin=False)

    log.warning("Connection rejected: invalid token")
    return None


def extract_token_from_query(path: str) -> str | None:
    """Extract token from WebSocket query string ?token=xxx."""
    try:
        parsed = urlparse(path)
        params = parse_qs(parsed.query)
        tokens = params.get("token", [])
        return tokens[0] if tokens else None
    except Exception:
        return None
