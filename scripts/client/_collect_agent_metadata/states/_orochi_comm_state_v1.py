"""Communication state scheme v1 (Layer B).

Pure function: A2A observations → ``{"label", "evidence", "version"}``.

Conservative — only emits coarse labels; deliberately avoids picking
"stuck" thresholds at this layer. Consumers that want to alert on
"working but silent for >N min" can read
``sac_a2a_observations.seconds_since_most_recent_event`` directly.

Labels:
    not-applicable    — agent has no A2A endpoint configured
    unreachable       — endpoint configured but the sidecar didn't respond
    idle              — endpoint healthy, no active tasks
    working           — at least one task in TASK_STATE_WORKING
    awaiting-input    — at least one task in TASK_STATE_INPUT_REQUIRED
    awaiting-auth     — at least one task in TASK_STATE_AUTH_REQUIRED
    mixed             — multiple non-terminal states present (rare)
"""

from __future__ import annotations

from typing import Any

VERSION = "v1"

# A2A protobuf state names that count as "active" (not yet settled).
_TERMINAL_STATES = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_FAILED",
    "TASK_STATE_REJECTED",
}


def derive_orochi_comm_state(obs: dict[str, Any]) -> dict[str, str]:
    """Apply the v1 decision tree to an A2A observations dict."""
    if not obs:
        return _verdict("not-applicable", "no observations")

    if not obs.get("endpoint_configured"):
        return _verdict(
            "not-applicable",
            obs.get("reachability_error") or "no a2a endpoint in agent YAML",
        )

    if not obs.get("endpoint_reachable"):
        return _verdict(
            "unreachable",
            obs.get("reachability_error") or "sidecar did not respond",
        )

    by_state: dict[str, int] = obs.get("tasks_by_state") or {}
    # Filter terminal states out — they don't contribute to current activity.
    active_by_state = {k: v for k, v in by_state.items() if k not in _TERMINAL_STATES}

    if not active_by_state:
        n_terminal = sum(by_state.values())
        if n_terminal:
            return _verdict(
                "idle",
                f"no active tasks ({n_terminal} terminal in store)",
            )
        return _verdict("idle", "no tasks in store")

    secs = obs.get("seconds_since_most_recent_event")
    secs_repr = f"{secs:.0f}s" if isinstance(secs, (int, float)) else "n/a"

    if len(active_by_state) > 1:
        return _verdict(
            "mixed",
            f"multiple active states: {active_by_state}; last event {secs_repr} ago",
        )

    only_state = next(iter(active_by_state))
    count = active_by_state[only_state]
    if only_state == "TASK_STATE_WORKING":
        return _verdict(
            "working",
            f"{count} working task(s); last event {secs_repr} ago",
        )
    if only_state == "TASK_STATE_INPUT_REQUIRED":
        return _verdict(
            "awaiting-input",
            f"{count} task(s) awaiting input; last event {secs_repr} ago",
        )
    if only_state == "TASK_STATE_AUTH_REQUIRED":
        return _verdict(
            "awaiting-auth",
            f"{count} task(s) awaiting auth; last event {secs_repr} ago",
        )
    if only_state == "TASK_STATE_SUBMITTED":
        return _verdict(
            "working",
            f"{count} submitted task(s) (executor not yet started); "
            f"last event {secs_repr} ago",
        )
    return _verdict(
        "mixed",
        f"unexpected state {only_state} (x{count}); last event {secs_repr} ago",
    )


def _verdict(label: str, evidence: str) -> dict[str, str]:
    return {"label": label, "evidence": evidence, "version": VERSION}
