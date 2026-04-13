"""Quota pressure escalation consumer (todo#272 hub side).

Producer side (head-spartan, branch feat/quota-pressure-producer) polls
`/api/oauth/usage` from each agent and pushes utilization figures into
the heartbeat. This module owns the *consumer* logic: it decides when
those figures cross thresholds and posts escalation messages.

State machine per (agent, window):
    ok -> warn        : post to #progress
    warn -> escalate  : post to #escalation AND #ywatanabe
    escalate -> ok    : post recovery to #progress (once)
    other transitions: silent

State is in-memory only via registry transient fields:
    quota_state_5h, quota_state_7d.
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


def _default_post(channel: str, text: str) -> None:  # pragma: no cover - exercised at integration time
    """Persist a system message into the workspace channel.

    Best-effort: swallow errors so quota_watch never breaks the heartbeat
    hot path. Workspace resolution is left to the caller (we post into
    the most recently registered workspace's channel by name).
    """
    try:
        from hub.models import Channel, Message, Workspace

        ws = Workspace.objects.order_by("id").first()
        if ws is None:
            return
        ch, _ = Channel.objects.get_or_create(workspace=ws, name=channel)
        Message.objects.create(
            workspace=ws, channel=ch, sender="orochi-quota-watch", content=text
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
