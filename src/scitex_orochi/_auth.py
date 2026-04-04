"""Orochi authentication -- token validation."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from scitex_orochi._config import OROCHI_TOKEN

log = logging.getLogger("orochi.auth")


def verify_token(token: str | None) -> bool:
    """Verify a connection token. Rejects if token is missing or wrong."""
    if not token:
        log.warning("Connection rejected: no token provided")
        return False
    if token != OROCHI_TOKEN:
        log.warning("Connection rejected: invalid token")
        return False
    return True


def extract_token_from_query(path: str) -> str | None:
    """Extract token from WebSocket query string ?token=xxx."""
    try:
        parsed = urlparse(path)
        params = parse_qs(parsed.query)
        tokens = params.get("token", [])
        return tokens[0] if tokens else None
    except Exception:
        return None
