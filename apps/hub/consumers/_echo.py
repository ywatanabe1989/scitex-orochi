"""Hub→agent echo round-trip publisher loop (#259, indicator #4).

Periodically sends a `{"type":"echo","nonce":"<uuid>"}` frame to every
connected agent. The agent's MCP-channel WebSocket client auto-replies
with `{"type":"echo_pong","nonce":"<same>","ts":<unix>}` (handled at
the WS-client layer — *not* a Claude round-trip).

The hub measures round-trip time, records ``last_echo_rtt_ms`` +
``last_echo_ok_ts`` + ``last_nonce_echo_at`` on the agent's registry
entry. The Agents-tab LED renderer (``renderAgentLeds`` in
``hub/static/hub/agent-badge.js``) reads ``last_nonce_echo_at`` and
flips the 4th LED from grey-dashed "pending" to green / yellow / red
based on age, with no further frontend changes.

Cadence is configurable via the ``OROCHI_ECHO_INTERVAL_SECONDS``
environment variable (default 30s — matched to the existing
``_hub_ping_loop`` cadence so a complete loss is noticed by both
indicators within one cycle, not two).

Backward-compatible: agents that never echo back keep functioning
(their 4th LED stays grey-pending). We never disconnect on a missing
echo. Unknown nonces in inbound ``echo_pong`` frames are dropped
silently.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

log = logging.getLogger("orochi.consumers")


def _read_interval_seconds() -> int:
    """Read the publisher cadence from the environment (default 30s).

    Constrained to a sane range — we don't want a misconfigured env
    var to flood the WS or, conversely, push the cadence above the
    LED's "stale" threshold (90s) and make every agent appear yellow.
    """
    raw = os.environ.get("OROCHI_ECHO_INTERVAL_SECONDS", "30")
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = 30
    if v < 5:
        v = 5
    if v > 60:
        v = 60
    return v


ECHO_INTERVAL_SECONDS = _read_interval_seconds()

# Bound on the per-agent in-flight nonce dict. Each entry is small
# (uuid + float) but unbounded growth would be a slow leak if an agent
# never replies. The cap is deliberately ~10× the expected steady-state
# in-flight count so transient bursts (network hiccups) don't evict
# legitimate replies.
MAX_INFLIGHT_NONCES = 32

# Drop nonces older than this many seconds — we'll never accept a pong
# that took longer than this anyway, and stale entries are pure noise
# in the in-flight dict.
NONCE_EXPIRY_SECONDS = 120


def _prune_expired(inflight: dict[str, float], now: float) -> None:
    """Remove entries older than NONCE_EXPIRY_SECONDS from inflight dict."""
    expired = [
        nonce
        for nonce, sent_at in inflight.items()
        if now - sent_at > NONCE_EXPIRY_SECONDS
    ]
    for n in expired:
        inflight.pop(n, None)


async def _hub_echo_loop(consumer) -> None:
    """Send periodic ``{"type":"echo","nonce":"<uuid>"}`` frames.

    Runs for the lifetime of the WebSocket connection. Cancelled from
    ``AgentConsumer.disconnect``. Exceptions other than
    ``CancelledError`` are logged and swallowed so a publisher crash
    cannot tear down the consumer (matches ``_hub_ping_loop`` semantics).

    The per-consumer in-flight nonce dict (``_echo_inflight``) is
    initialised lazily here so the consumer's ``__init__`` doesn't need
    to know about it. It's read by ``handle_echo_pong`` to compute RTT.
    """
    if not hasattr(consumer, "_echo_inflight"):
        consumer._echo_inflight = {}
    inflight: dict[str, float] = consumer._echo_inflight

    try:
        while True:
            await asyncio.sleep(ECHO_INTERVAL_SECONDS)
            now = time.time()
            _prune_expired(inflight, now)
            # If we've hit the cap, evict the oldest entry so a single
            # silent agent can't permanently lock new probes out.
            if len(inflight) >= MAX_INFLIGHT_NONCES:
                oldest = min(inflight, key=inflight.get)
                inflight.pop(oldest, None)

            nonce = uuid.uuid4().hex
            inflight[nonce] = now
            try:
                await consumer.send_json({"type": "echo", "nonce": nonce})
            except Exception:  # noqa: BLE001
                log.exception(
                    "echo send failed for %s",
                    getattr(consumer, "agent_name", "?"),
                )
                return
    except asyncio.CancelledError:
        raise
