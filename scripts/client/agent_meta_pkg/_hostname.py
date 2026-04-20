"""Canonical hostname resolution for the agent dashboard (todo#55)."""

from __future__ import annotations

import socket


def _resolve_canonical_hostname() -> str:
    """Best-effort canonical hostname for dashboard display (todo#55).

    On Linux ``socket.getfqdn()`` usually returns a sensible
    ``host.example.com``. On macOS (and some containers) it can return the
    IPv6 loopback PTR — e.g. ``1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0
    .0.0.0.0.0.0.0.0.0.0.ip6.arpa`` — which is worse than useless. In that
    case we prefer ``socket.gethostname()`` which returns the user-meaningful
    ``*.local`` / ``*.localdomain`` name the user recognises.
    """
    try:
        fqdn = (socket.getfqdn() or "").strip()
    except Exception:
        fqdn = ""
    try:
        short = (socket.gethostname() or "").strip()
    except Exception:
        short = ""
    looks_bogus = (
        not fqdn
        or fqdn.endswith(".arpa")
        or fqdn == "localhost"
        or fqdn == "localhost.localdomain"
    )
    if looks_bogus:
        return short
    return fqdn
