"""Token-based authentication for Orochi connections."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from orochi.config import OROCHI_TOKEN

log = logging.getLogger("orochi.auth")


def verify_token(token: str | None) -> bool:
    """Verify a token against the configured OROCHI_TOKEN.

    Returns True if:
    - No OROCHI_TOKEN is configured (auth disabled)
    - The provided token matches OROCHI_TOKEN
    """
    if not OROCHI_TOKEN:
        return True
    if not token:
        log.warning("Auth failed: no token provided")
        return False
    if token != OROCHI_TOKEN:
        log.warning("Auth failed: invalid token")
        return False
    return True


def extract_token_from_query(path: str) -> str | None:
    """Extract token from WebSocket query string: ws://host:port/?token=xxx."""
    try:
        parsed = urlparse(path)
        params = parse_qs(parsed.query)
        tokens = params.get("token", [])
        return tokens[0] if tokens else None
    except Exception:
        return None
