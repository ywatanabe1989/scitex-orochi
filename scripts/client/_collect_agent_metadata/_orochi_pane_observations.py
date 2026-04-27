"""Layer A — pane observations (pure data collection, no interpretation).

Reads primitive facts from the agent's tmux pane content. Returns a flat
dict the state-definition modules in ``states/`` consume.

Intentionally has NO opinions about what the facts mean — no "stale",
no "idle", no decisions. Just measurements:

    - which busy markers matched
    - which auth/permission/y_n markers are visible
    - the pane content digest (sha1[:16])
    - how many consecutive cycles the digest has been unchanged
    - whether the empty-`❯` idle prompt is visible
    - what (if any) draft text is in the compose box

The pattern catalogues themselves (``_BUSY_ANIMATION_MARKERS`` etc.) are
re-exported from ``_classifier.py`` so we don't duplicate the literal
strings; once Layer B is fully migrated, the catalogues can move here
permanently.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from ._classifier import (
    _AUTH_MARKERS,
    _BUSY_ANIMATION_MARKERS,
    _BUSY_ANIMATION_REGEXES,
    _BYPASS_MARKERS,
    _COMPOSE_CHEVRON,
    _DEVCHAN_MARKERS,
    _PROGRESS_MARKERS,
    _YN_MARKERS,
)

_STATE_DIR = Path(
    os.environ.get(
        "SCITEX_FLEET_CLASSIFIER_STATE_DIR",
        str(Path.home() / ".local" / "state" / "scitex" / "fleet-classifier"),
    )
)


def _pane_digest(tail_clean: str, full_pane: str) -> str:
    """SHA1[:16] of cleaned tail + full pane — the cross-cycle stagnation key."""
    h = hashlib.sha1()
    h.update((tail_clean or "").encode("utf-8", errors="replace"))
    h.update(b"\0")
    h.update((full_pane or "").encode("utf-8", errors="replace"))
    return h.hexdigest()[:16]


def _load_state(agent: str) -> tuple[str, int]:
    if not agent:
        return "", 0
    path = _STATE_DIR / f"{agent}.state"
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return "", 0
    parts = raw.split("\t", 1)
    if len(parts) != 2:
        return "", 0
    digest = parts[0].strip()
    try:
        count = int(parts[1].strip())
    except (TypeError, ValueError):
        count = 0
    return digest, max(0, count)


def _save_state(agent: str, digest: str, count: int) -> None:
    if not agent:
        return
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        (_STATE_DIR / f"{agent}.state").write_text(
            f"{digest}\t{count}\n", encoding="utf-8"
        )
    except OSError:
        pass


def _update_stagnation_count(agent: str, digest: str) -> int:
    """Increment unchanged-cycle counter for ``agent``; reset on digest change."""
    prev_digest, prev_count = _load_state(agent)
    if prev_digest and prev_digest == digest:
        count = prev_count + 1
    else:
        count = 0
    _save_state(agent, digest, count)
    return count


def _read_compose(tail: str) -> tuple[str, bool]:
    """Return (compose_text, chevron_seen) for the last compose line."""
    compose = ""
    chevron_seen = False
    for line in (tail or "").splitlines()[-12:]:
        stripped = line.lstrip()
        if stripped.startswith(_COMPOSE_CHEVRON):
            chevron_seen = True
            rest = stripped[len(_COMPOSE_CHEVRON) :]
            compose = rest.lstrip(" \t\u00a0").rstrip()
    return compose, chevron_seen


def collect_orochi_pane_observations(
    tail_clean: str,
    full_pane: str,
    agent: str = "",
) -> dict[str, Any]:
    """Layer A entry point: pane content → flat dict of primitive facts.

    Pass the result to a state-definition module (``states/_pane_state_v3.py``)
    to get an interpreted label. The two layers are independently testable;
    new state schemes can be added by writing a new module that consumes
    the same observation shape.
    """
    if not tail_clean and not full_pane:
        return {}

    hay = (full_pane or "") + "\n" + (tail_clean or "")
    busy_marker_hits = [m for m in _BUSY_ANIMATION_MARKERS if m in hay]
    busy_regex_hits = [
        rationale for pat, rationale in _BUSY_ANIMATION_REGEXES if pat.search(hay)
    ]
    auth_marker_hits = [m for m in _AUTH_MARKERS if m in hay]

    compose_text, compose_chevron_seen = _read_compose(tail_clean or "")

    digest = _pane_digest(tail_clean or "", full_pane or "")
    unchanged_cycles = _update_stagnation_count(agent, digest) if agent else 0

    return {
        "digest": digest,
        "unchanged_cycles": unchanged_cycles,
        "busy_marker_hits": busy_marker_hits,
        "busy_regex_hits": busy_regex_hits,
        "auth_marker_hits": auth_marker_hits,
        "progress_marker_present": any(m in hay for m in _PROGRESS_MARKERS),
        "bypass_markers_present": all(m in hay for m in _BYPASS_MARKERS),
        "devchan_marker_present": any(m in hay for m in _DEVCHAN_MARKERS),
        "yn_marker_present": any(m in hay for m in _YN_MARKERS),
        "compose_text": compose_text,
        "compose_chevron_seen": compose_chevron_seen,
        "compose_is_empty": compose_chevron_seen and not compose_text,
    }
