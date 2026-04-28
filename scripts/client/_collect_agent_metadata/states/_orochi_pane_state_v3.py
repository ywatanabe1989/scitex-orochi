"""Pane state scheme v3 (Layer B).

Pure function: pane observations → ``{"label", "evidence", "version"}``.

Version history:
    v1 — original digest-based stagnation only
    v2 — added busy-animation marker carve-out (false-positive guard)
    v3 — added empty-`❯` idle-prompt carve-out (2026-04-27) so an agent
         peacefully waiting at the prompt is `idle`, not `stale`
"""

from __future__ import annotations

from typing import Any

VERSION = "v3"
STALE_CYCLES_THRESHOLD = 3


def derive_orochi_pane_state(obs: dict[str, Any]) -> dict[str, str]:
    """Apply the v3 decision tree to a pane observations dict.

    Order matters — checks proceed cheapest-and-most-specific first so an
    auth error never gets shadowed by a stagnation verdict, etc.
    """
    if not obs:
        return _verdict("", "no observations")

    if obs.get("progress_marker_present"):
        return _verdict("running", "esc-to-interrupt visible (token streaming)")

    if obs.get("auth_marker_hits"):
        hits = obs["auth_marker_hits"]
        return _verdict("auth_error", f"auth markers matched: {hits}")

    if obs.get("bypass_markers_present"):
        return _verdict(
            "bypass_permissions_prompt",
            "bypass-permissions prompt visible (1.+2. accept lines)",
        )

    if obs.get("devchan_marker_present"):
        return _verdict("dev_channels_prompt", "dev-channels prompt visible")

    if obs.get("yn_marker_present"):
        return _verdict("y_n_prompt", "y/n confirmation prompt visible")

    compose = obs.get("compose_text") or ""
    if len(compose) >= 3 and not compose.startswith("> "):
        excerpt = compose[:60]
        return _verdict(
            "compose_pending_unsent", f"draft text in compose box: {excerpt!r}"
        )

    cycles = int(obs.get("unchanged_cycles") or 0)
    busy_hits: list[Any] = list(obs.get("busy_marker_hits") or []) + list(
        obs.get("busy_regex_hits") or []
    )

    if cycles >= STALE_CYCLES_THRESHOLD and not busy_hits:
        if obs.get("compose_is_empty"):
            return _verdict(
                "idle",
                f"empty `❯ ` chevron present, unchanged {cycles} cycles "
                "(self-reporting alive idle)",
            )
        return _verdict(
            "stale",
            f"unchanged {cycles} cycles, no busy markers, no idle prompt",
        )

    if busy_hits:
        return _verdict(
            "idle",
            f"busy markers seen: {busy_hits[:2]}"
            + (f" (+{len(busy_hits) - 2} more)" if len(busy_hits) > 2 else ""),
        )

    return _verdict("idle", "default — no escalation triggers fired")


def _verdict(label: str, evidence: str) -> dict[str, str]:
    return {"label": label, "evidence": evidence, "version": VERSION}
