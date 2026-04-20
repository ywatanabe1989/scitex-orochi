"""Agent decision-transparency pane-state classifier (todo#418).

Mirrors the state labels the fleet-prompt-actuator +
scitex_agent_container.runtimes.prompts module use, but inlined so
agent_meta stays dependency-free. The classifier runs on every push
(~30 s), reads the pane tail, and emits a stable label + verbatim
stuck-prompt text so the hub Agents tab can render a badge + expand
the prompt ywatanabe needs to see.
"""

from __future__ import annotations

_COMPOSE_CHEVRON = "❯"
_PROGRESS_MARKERS = ("esc to interrupt",)
_AUTH_MARKERS = ("/login", "Invalid API key", "authentication failed")
_BYPASS_MARKERS = ("Bypass Permissions", "2. Yes, I accept")
_DEVCHAN_MARKERS = ("1. I am using this for local development",)
_YN_MARKERS = ("y/n", "[y/N]", "[Y/n]")


def _extract_compose_text(tail: str) -> str:
    """Return the content after the `❯` chevron on the last compose line, or ''."""
    compose = ""
    for line in tail.splitlines()[-12:]:
        stripped = line.lstrip()
        if stripped.startswith(_COMPOSE_CHEVRON):
            rest = stripped[len(_COMPOSE_CHEVRON) :]
            compose = rest.lstrip(" \t\u00a0").rstrip()
    return compose


def _classify_pane_state(tail_clean: str, full_pane: str) -> str:
    """Classify the agent's current pane state into one of:
    running / compose_pending_unsent / bypass_permissions_prompt /
    dev_channels_prompt / y_n_prompt / auth_error / idle / ""

    Conservative — returns "" when we can't confidently classify.
    The full_pane string is the raw ~30-line capture used for marker
    scans; tail_clean is the channel-inbound-stripped tail used for
    compose-box detection (so ← scitex-orochi lines don't fool us).
    """
    if not full_pane and not tail_clean:
        return ""
    hay = (full_pane or "") + "\n" + (tail_clean or "")
    if any(m in hay for m in _PROGRESS_MARKERS):
        return "running"
    if any(m in hay for m in _AUTH_MARKERS):
        return "auth_error"
    if all(m in hay for m in _BYPASS_MARKERS):
        return "bypass_permissions_prompt"
    if any(m in hay for m in _DEVCHAN_MARKERS):
        return "dev_channels_prompt"
    if any(m in hay for m in _YN_MARKERS):
        return "y_n_prompt"
    compose = _extract_compose_text(tail_clean)
    if len(compose) >= 3 and not compose.startswith("> "):
        return "compose_pending_unsent"
    return "idle"


def _extract_stuck_prompt(tail_clean: str, full_pane: str) -> str:
    """Return the verbatim stuck-prompt text the agent is blocked on.

    Empty string when the agent isn't stuck. For `compose_pending_unsent`
    we return the chevron-line content; for the other prompt classes
    (bypass/dev-channels/y_n) we return a short excerpt from the tail
    containing the marker line, so ywatanabe can see *exactly* what text
    the agent is facing.
    """
    state = _classify_pane_state(tail_clean, full_pane)
    if state in ("running", "idle", ""):
        return ""
    if state == "compose_pending_unsent":
        return _extract_compose_text(tail_clean)[:500]
    hay_lines = (tail_clean or "").splitlines()[-12:]
    return "\n".join(hay_lines)[:500]
