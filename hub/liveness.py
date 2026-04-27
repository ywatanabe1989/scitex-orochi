"""Liveness classification from pane_capture hash diffs (todo#270).

Detects whether an agent is alive by comparing SHA1 hashes of the tail
(last 10 lines) of its tmux/screen pane across consecutive heartbeats.

States (mutually exclusive):
- "moving"      — pane changed within the last 60s
- "idle"        — pane unchanged for 60-600s (normal waiting)
- "stuck"       — pane unchanged for >600s and not in a known capped state
- "quota-capped"— OAuth usage indicates 5h utilization >= 1.0
- "unknown"     — no history yet or no pane data

The history is purely in-memory (per-process). Hub restarts reset it,
which is intentional: liveness is a moment-to-moment signal, not an
audit log.
"""

from __future__ import annotations

import hashlib
import threading
import time

# Per-agent ring buffer: { agent_name: [(ts, hash), ...] } (cap 10)
_HISTORY: dict[str, list[tuple[float, str]]] = {}
_HISTORY_CAP = 10
_LOCK = threading.Lock()

MOVING_WINDOW_S = 60
IDLE_WINDOW_S = 600


def compute_pane_hash(pane_lines: list[str]) -> str:
    """SHA1 of the last 10 lines, whitespace-normalized.

    Trailing whitespace is stripped per line (screen padding) before
    joining. An empty input is hashed as the empty string so the caller
    still gets a deterministic value.
    """
    if not pane_lines:
        normalized = ""
    else:
        tail = pane_lines[-10:]
        normalized = "\n".join(line.rstrip() for line in tail)
    return hashlib.sha1(normalized.encode("utf-8", "replace")).hexdigest()


def record_hash(name: str, h: str, *, now: float | None = None) -> list[tuple[float, str]]:
    """Append (ts, hash) to the per-agent ring buffer (cap 10)."""
    ts = now if now is not None else time.time()
    with _LOCK:
        buf = _HISTORY.setdefault(name, [])
        buf.append((ts, h))
        if len(buf) > _HISTORY_CAP:
            del buf[: len(buf) - _HISTORY_CAP]
        # Return a snapshot so callers don't share the mutable list.
        return list(buf)


def get_history(name: str) -> list[tuple[float, str]]:
    with _LOCK:
        return list(_HISTORY.get(name, []))


def reset(name: str | None = None) -> None:
    """Clear history for one agent or all (used by tests)."""
    with _LOCK:
        if name is None:
            _HISTORY.clear()
        else:
            _HISTORY.pop(name, None)


def classify_liveness(
    current_hash: str | None,
    history: list[tuple[float, str]],
    quota_capped: bool,
    *,
    now: float | None = None,
) -> str:
    """Classify the agent's liveness from its pane-hash history.

    `history` is the post-append ring buffer (most recent entry last).
    `current_hash` may be None when the agent did not push pane_capture
    on this tick, in which case we still classify based on prior history
    so the dashboard doesn't flicker back to unknown.
    """
    if quota_capped:
        return "quota-capped"
    if not history:
        return "unknown"

    now = now if now is not None else time.time()
    last_ts, last_hash = history[-1]

    # Find the most recent prior change (a hash that differs from last_hash).
    last_change_ts = last_ts
    for ts, h in reversed(history[:-1]):
        if h != last_hash:
            # last_change_ts = first ts at which last_hash appeared
            break
        last_change_ts = ts

    age = now - last_change_ts
    if age < MOVING_WINDOW_S:
        return "moving"
    if age < IDLE_WINDOW_S:
        return "idle"
    return "stuck"
