"""Quota pressure escalation consumer (todo#272 hub side).

Producer side (agent-container `agent_meta.py --push` loop) reads the
Anthropic `/api/oauth/usage` endpoint + Claude Code statusline and
pushes utilization figures into the heartbeat as
``quota_5h_used_pct`` / ``quota_7d_used_pct`` +
``quota_5h_reset_at`` / ``quota_7d_reset_at``. This module owns the
*consumer* logic: it decides when those figures cross thresholds and
posts escalation messages so the fleet (or ywatanabe) can migrate
accounts *before* the hard cap triggers a 100% wedge.

State machine per (agent, window):
    ok -> warn        : post to #progress
    warn -> escalate  : post to #escalation AND #ywatanabe
    escalate -> ok    : post recovery to #progress (once)
    other transitions: silent (no spam on downshifts / partial recovery)

State is in-memory only via registry transient fields:
    quota_state_5h, quota_state_7d.

Entry point for the heartbeat hot path is
:func:`check_agent_quota_pressure` — it reads the current utilization
off the in-memory registry, runs :func:`evaluate`, and writes the new
per-window state back so transitions fire exactly once per crossing.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger("orochi.quota_watch")

# Threshold table per head-spartan msg#7770.
WARN_5H = 0.80
ESCALATE_5H = 0.95
WARN_7D = 0.85
ESCALATE_7D = 0.95

WINDOWS = ("5h", "7d")
STATE_OK = "ok"
STATE_WARN = "warn"
STATE_ESCALATE = "escalate"


def _classify(util: float, window: str) -> str:
    if util is None:
        return STATE_OK
    if window == "5h":
        if util >= ESCALATE_5H:
            return STATE_ESCALATE
        if util >= WARN_5H:
            return STATE_WARN
        return STATE_OK
    if window == "7d":
        if util >= ESCALATE_7D:
            return STATE_ESCALATE
        if util >= WARN_7D:
            return STATE_WARN
        return STATE_OK
    return STATE_OK


def _format_pct(util: float) -> str:
    try:
        return f"{int(round(util * 100))}%"
    except Exception:
        return "?%"


def _format_reset(reset_at: Optional[str]) -> str:
    if not reset_at:
        return "soon"
    return f"at {reset_at}"


# Posting callback type: (channel, text) -> None
PostFn = Callable[[str, str], None]


def _make_workspace_post(workspace_id: int) -> PostFn:
    """Build a PostFn that writes to a specific workspace.

    Best-effort: swallow errors so quota_watch never breaks the heartbeat
    hot path. The workspace id is captured at heartbeat time so
    multi-workspace hubs can't cross-post quota warnings into the wrong
    workspace (matches the per-agent ``workspace_id`` stored in the
    registry).
    """

    def _post(channel: str, text: str) -> None:
        try:
            from hub.models import Channel, Message

            ch, _ = Channel.objects.get_or_create(
                workspace_id=workspace_id, name=channel
            )
            Message.objects.create(
                workspace_id=workspace_id,
                channel=ch,
                sender="orochi-quota-watch",
                sender_type="agent",
                content=text,
            )
        except Exception:
            log.exception("quota_watch post failed for %s", channel)

    return _post


def _default_post(channel: str, text: str) -> None:  # pragma: no cover - exercised at integration time
    """Fallback post used when no workspace_id is known."""
    try:
        from hub.models import Channel, Message, Workspace

        ws = Workspace.objects.order_by("id").first()
        if ws is None:
            return
        ch, _ = Channel.objects.get_or_create(workspace=ws, name=channel)
        Message.objects.create(
            workspace=ws,
            channel=ch,
            sender="orochi-quota-watch",
            sender_type="agent",
            content=text,
        )
    except Exception:
        log.exception("quota_watch default_post failed for %s", channel)


def evaluate(
    agent_name: str,
    *,
    util_5h: Optional[float],
    util_7d: Optional[float],
    reset_5h: Optional[str],
    reset_7d: Optional[str],
    prev_state_5h: str,
    prev_state_7d: str,
    post: PostFn = _default_post,
) -> tuple[str, str, list[tuple[str, str]]]:
    """Run the quota state machine for one heartbeat.

    Returns (new_state_5h, new_state_7d, posts) where ``posts`` is the
    list of (channel, text) pairs that were emitted via ``post``.
    """
    posts: list[tuple[str, str]] = []
    new_5h = _classify(util_5h, "5h") if util_5h is not None else prev_state_5h or STATE_OK
    new_7d = _classify(util_7d, "7d") if util_7d is not None else prev_state_7d or STATE_OK

    for window, util, reset, prev, new in (
        ("5h", util_5h, reset_5h, prev_state_5h or STATE_OK, new_5h),
        ("7d", util_7d, reset_7d, prev_state_7d or STATE_OK, new_7d),
    ):
        if util is None:
            continue
        msgs = _transition_messages(agent_name, window, util, reset, prev, new)
        for channel, text in msgs:
            try:
                post(channel, text)
            except Exception:
                log.exception("quota_watch post failed (%s)", channel)
            posts.append((channel, text))

    return new_5h, new_7d, posts


def _transition_messages(
    agent: str,
    window: str,
    util: float,
    reset_at: Optional[str],
    prev: str,
    new: str,
) -> list[tuple[str, str]]:
    if prev == new:
        return []
    pct = _format_pct(util)
    when = _format_reset(reset_at)

    # ok -> warn
    if prev == STATE_OK and new == STATE_WARN:
        return [
            (
                "#progress",
                f"{agent} {window} utilization {pct} (resets {when})",
            )
        ]
    # warn -> escalate (or ok -> escalate, treat as escalate)
    if new == STATE_ESCALATE and prev != STATE_ESCALATE:
        text = (
            f"{agent} {window} utilization {pct} — ESCALATE (resets {when})"
        )
        return [("#escalation", text), ("#ywatanabe", text)]
    # escalate -> ok recovery
    if prev == STATE_ESCALATE and new == STATE_OK:
        return [
            (
                "#progress",
                f"{agent} {window} recovered — utilization {pct}",
            )
        ]
    # warn -> ok or escalate -> warn: silent (warn->ok is a downshift,
    # escalate->warn is partial recovery; we only ping on full recovery
    # to avoid spam per ywatanabe msg#7788).
    return []


def _coerce_utilization(value) -> Optional[float]:
    """Normalize quota payload value to a 0..1 utilization float.

    Producers push either a fraction (0..1) or a percentage (0..100).
    Accept both so quota_watch doesn't misfire when the producer
    convention changes. Returns ``None`` for non-numeric / missing
    values so classify() can leave the state unchanged.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    # Treat anything > 1.5 as a percentage (0..100 scale) and rescale.
    # Threshold chosen conservatively so a legitimate over-quota value
    # like 1.05 (5% into hard cap) is still read as a fraction.
    if f > 1.5:
        f = f / 100.0
    if f < 0.0:
        return 0.0
    return f


def check_agent_quota_pressure(name: str, post: Optional[PostFn] = None) -> None:
    """Run the quota state machine for one agent based on registry state.

    Called from the heartbeat hot path (REST
    ``/api/agents/register/`` + WS ``agent_heartbeat`` handler). Reads
    the agent's current quota utilization + reset timestamps + previous
    per-window state from the in-memory registry, calls
    :func:`evaluate`, and writes back the new per-window state so the
    state machine transitions fire exactly once per crossing.

    Best-effort: any exception is logged and swallowed — quota_watch
    must never block or crash the heartbeat path.

    Args:
        name: agent name as registered in ``hub.registry._agents``.
        post: override for the post callback (mainly for tests). When
            ``None``, a post function scoped to the agent's
            ``workspace_id`` is constructed on the fly.
    """
    try:
        from hub.registry import _agents, _lock

        with _lock:
            agent = _agents.get(name)
            if not agent:
                return
            util_5h_raw = agent.get("quota_5h_used_pct")
            util_7d_raw = agent.get("quota_7d_used_pct")
            reset_5h = agent.get("quota_5h_reset_at") or None
            reset_7d = agent.get("quota_7d_reset_at") or None
            prev_5h = agent.get("quota_state_5h") or STATE_OK
            prev_7d = agent.get("quota_state_7d") or STATE_OK
            workspace_id = agent.get("workspace_id")

        util_5h = _coerce_utilization(util_5h_raw)
        util_7d = _coerce_utilization(util_7d_raw)
        if util_5h is None and util_7d is None:
            return

        if post is None:
            if workspace_id is None:
                post = _default_post
            else:
                post = _make_workspace_post(int(workspace_id))

        new_5h, new_7d, _ = evaluate(
            name,
            util_5h=util_5h,
            util_7d=util_7d,
            reset_5h=reset_5h,
            reset_7d=reset_7d,
            prev_state_5h=prev_5h,
            prev_state_7d=prev_7d,
            post=post,
        )

        with _lock:
            agent = _agents.get(name)
            if agent is not None:
                agent["quota_state_5h"] = new_5h
                agent["quota_state_7d"] = new_7d
    except Exception:
        log.exception("check_agent_quota_pressure failed for %s", name)
