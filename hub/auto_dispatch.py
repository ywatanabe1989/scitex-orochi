"""Server-side auto-dispatch for idle ``head-*`` agents (Layer 1 redesign).

Replaces the client-side ``scripts/client/auto-dispatch-probe.sh`` daemon
(PR #320) with hub-side detection driven off the heartbeat hot path.

Design (lead msg#16388, ywatanabe msg#16380)
--------------------------------------------

On every heartbeat from a ``head-<host>`` agent:

1. Compare the newly written ``subagent_count`` with the prior reading
   held in ``hub.registry._agents[<name>]``.
2. Maintain a per-head ``idle_streak`` counter. Zero reading increments
   the streak, any non-zero reading resets it (but the cooldown window
   is preserved — a head that briefly forks then collapses to zero
   should not immediately get re-dispatched).
3. When the streak reaches ``SCITEX_AUTO_DISPATCH_STREAK_THRESHOLD``
   (default 2 — roughly two heartbeat cycles of stillness), fire an
   auto-dispatch DM to the head's own DM channel with itself (the
   canonical ``dm:agent:head-<host>|human:orochi-auto-dispatch`` lane)
   so the head's :class:`AgentConsumer` receives it as a normal chat
   frame and the head's Claude parses the instruction.
4. After firing, mark the cooldown (``SCITEX_AUTO_DISPATCH_COOLDOWN_SECONDS``,
   default 900 = 15 min). No further auto-dispatches to the same head
   until the cooldown expires. Streak is reset on fire.

Kill switch
-----------

``SCITEX_AUTO_DISPATCH_DISABLED=1`` — any value other than ``"1"`` leaves
the feature enabled. Best-effort: any exception raised inside the auto-
dispatch path is logged and swallowed; the heartbeat hot path must never
fail because of auto-dispatch.

State location
--------------

Streak counter and cooldown timestamp live on the in-memory agent
entry (``_agents[name]["idle_streak"]`` / ``_agents[name]["auto_dispatch_last_fire_ts"]``),
so they survive regular heartbeats via ``_register.register_agent``'s
prev-preserve block (see changes there). Hub restart resets the state,
which is acceptable — an idle head will re-trigger on the next two
heartbeats.

Todo-selection
--------------

We shell out to ``scripts/client/auto-dispatch-pick-todo.py`` as a
subprocess rather than inlining the ``gh issue list`` logic. The helper
is already unit-tested (PR #320 test_pick_todo.py) and has its own
failure contract ("print null on no match, never crash"). Subprocess
timeout = 20s — if ``gh`` is unauth or slow, auto-dispatch silently
skips this cycle.

Hooks
-----

Entry point: :func:`check_agent_auto_dispatch` — invoked from
``hub/registry/_heartbeat.py::update_heartbeat`` after the quota
pressure check. Only fires for agents whose name starts with
``head-`` — non-head agents (workers, managers, healers) are skipped.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("orochi.auto_dispatch")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Lane label per head host. Source of truth: lead msg#15975 /
# auto-dispatch-probe.sh. Kept in sync.
LANE_FOR_HOST: dict[str, str] = {
    "mba": "infrastructure",
    "nas": "hub-admin",
    "spartan": "specialized-domain",
    "ywata-note-win": "specialized-wsl-access",
}

# Sender name used when the hub writes the auto-dispatch message into a
# head's DM channel. Kept distinct from ``orochi-quota-watch`` so any
# future audit / filter can tell the two sources apart.
AUTO_DISPATCH_SENDER = "orochi-auto-dispatch"


def _env_int(name: str, default: int) -> int:
    """Read an integer env var with a fallback."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _streak_threshold() -> int:
    """How many consecutive zero-subagent-count readings before firing."""
    return max(_env_int("SCITEX_AUTO_DISPATCH_STREAK_THRESHOLD", 2), 1)


def _cooldown_seconds() -> int:
    """Per-head minimum gap between auto-dispatches, in seconds."""
    return max(_env_int("SCITEX_AUTO_DISPATCH_COOLDOWN_SECONDS", 900), 0)


def _is_disabled() -> bool:
    """Kill switch. Any value except exactly ``"1"`` is "enabled"."""
    return os.environ.get("SCITEX_AUTO_DISPATCH_DISABLED", "0") == "1"


def _head_host_from_name(agent_name: str) -> Optional[str]:
    """Extract ``mba`` from ``head-mba``. Returns None for non-head agents."""
    if not agent_name or not agent_name.startswith("head-"):
        return None
    host = agent_name[len("head-") :]
    return host or None


# ---------------------------------------------------------------------------
# Todo selection (subprocess to auto-dispatch-pick-todo.py)
# ---------------------------------------------------------------------------

_PICK_HELPER_LOCK = threading.Lock()
_PICK_HELPER_PATH: Optional[Path] = None


def _pick_helper_path() -> Optional[Path]:
    """Locate ``scripts/client/auto-dispatch-pick-todo.py`` once and cache it.

    The hub process runs from the repo root so a relative ``scripts/``
    path is the canonical location. Operators can override via
    ``SCITEX_AUTO_DISPATCH_PICK_HELPER`` (absolute path).
    """
    global _PICK_HELPER_PATH
    with _PICK_HELPER_LOCK:
        if _PICK_HELPER_PATH is not None:
            return _PICK_HELPER_PATH if _PICK_HELPER_PATH.exists() else None
        override = os.environ.get("SCITEX_AUTO_DISPATCH_PICK_HELPER")
        if override:
            candidate = Path(override)
        else:
            # hub/auto_dispatch.py → repo root is parents[1].
            candidate = Path(__file__).resolve().parents[1] / "scripts" / "client" / "auto-dispatch-pick-todo.py"
        _PICK_HELPER_PATH = candidate
        return candidate if candidate.exists() else None


def _run_pick_todo(lane: str, timeout_s: int = 20) -> Optional[dict]:
    """Invoke the pick-todo helper and return the chosen issue dict or None.

    Swallows all exceptions — auto-dispatch must never raise into the
    heartbeat hot path. A missing helper, missing ``gh``, ``gh`` unauth,
    or helper timeout all result in ``None`` (no dispatch this cycle).
    """
    path = _pick_helper_path()
    if path is None:
        log.debug("auto_dispatch: pick helper not found at expected path")
        return None
    try:
        proc = subprocess.run(
            ["python3", str(path), "--lane", lane],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    out = (proc.stdout or "").strip()
    if not out or out == "null":
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    # Minimal sanity: must have integer number and non-empty title.
    if not data.get("number") or not data.get("title"):
        return None
    return data


# ---------------------------------------------------------------------------
# Message composition + DM fan-out
# ---------------------------------------------------------------------------


def _compose_dispatch_text(streak: int, pick: Optional[dict], cooldown_s: int) -> str:
    """Build the Claude-visible instruction text.

    Shape matches the spec in lead msg#16388. When no todo matches the
    lane we still fire (the stillness itself is the signal); the head's
    Claude can then choose what to do from its own backlog / context.
    """
    cooldown_min = max(cooldown_s // 60, 1)
    if pick is None:
        candidate = "no open todo matched this lane — pick from your own backlog"
    else:
        title = (pick.get("title") or "").strip()
        candidate = f"todo#{pick['number']} — {title} — pick and fork a subagent for it"
    return (
        f"[auto-dispatch] you have been idle for {streak} cycles. "
        f"Pick a high-priority todo from your lane and fork a subagent immediately. "
        f"Candidate: {candidate}. "
        f"Cooldown: no further auto-dispatches for {cooldown_min}min."
    )


def _canonical_auto_dispatch_dm_name(agent_name: str) -> str:
    """Build the canonical DM channel name for hub → head auto-dispatch.

    Uses ``agent:head-<host>`` for the head principal and
    ``human:orochi-auto-dispatch`` for the hub-synth sender. Names are
    sorted to match ``_dm_canonical_name``.
    """
    agent_key = f"agent:{agent_name}"
    sender_key = f"human:{AUTO_DISPATCH_SENDER}"
    keys = sorted([agent_key, sender_key])
    return "dm:" + "|".join(keys)


def _post_dispatch_message(agent_name: str, workspace_id: int, text: str, metadata: dict) -> Optional[int]:
    """Persist + broadcast the dispatch DM. Returns the new Message.id or None.

    Mirrors the fan-out shape in ``hub.mentions.expand_mentions_and_notify``:

      1. Ensure a sender ``User`` row (``orochi-auto-dispatch``) + a
         ``WorkspaceMember`` row for the workspace.
      2. Lazy-create the DM channel via ``_ensure_dm_channel``.
      3. Insert a :class:`Message` with ``metadata["kind"]="auto-dispatch"``.
      4. ``group_send`` on the DM channel group so the head's
         ``AgentConsumer`` delivers it live as a chat frame.

    Best-effort at every step — any failure is logged and returns None.
    """
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        from django.contrib.auth.models import User

        from hub.consumers import _sanitize_group
        from hub.models import Message, Workspace, WorkspaceMember
        from hub.views.api._dms import _ensure_dm_channel

        try:
            workspace = Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist:
            log.warning("auto_dispatch: workspace %s missing — skip", workspace_id)
            return None

        # Ensure the hub-synth sender user + workspace membership exist.
        sender_user, _ = User.objects.get_or_create(
            username=AUTO_DISPATCH_SENDER,
            defaults={
                "email": f"{AUTO_DISPATCH_SENDER}@agents.orochi.local",
                "is_active": True,
            },
        )
        WorkspaceMember.objects.get_or_create(
            user=sender_user,
            workspace=workspace,
            defaults={"role": "member"},
        )

        dm_name = _canonical_auto_dispatch_dm_name(agent_name)
        dm_channel = _ensure_dm_channel(workspace, dm_name)
        if dm_channel is None:
            log.warning("auto_dispatch: could not resolve DM channel %s", dm_name)
            return None

        dm_msg = Message.objects.create(
            workspace=workspace,
            channel=dm_channel,
            sender=AUTO_DISPATCH_SENDER,
            sender_type="agent",
            content=text,
            metadata=metadata,
        )

        # Broadcast so any already-connected AgentConsumer delivers it
        # as a normal chat.message frame immediately.
        layer = get_channel_layer()
        if layer is not None:
            group = _sanitize_group(f"channel_{workspace.id}_{dm_name}")
            try:
                async_to_sync(layer.group_send)(
                    group,
                    {
                        "type": "chat.message",
                        "id": dm_msg.id,
                        "sender": AUTO_DISPATCH_SENDER,
                        "sender_type": "agent",
                        "channel": dm_name,
                        "kind": "dm",
                        "text": text,
                        "ts": dm_msg.ts.isoformat(),
                        "metadata": metadata,
                    },
                )
            except Exception:
                log.exception("auto_dispatch: group_send failed for %s", dm_name)

        return dm_msg.id
    except Exception:
        log.exception("auto_dispatch: _post_dispatch_message failed for %s", agent_name)
        return None


# ---------------------------------------------------------------------------
# Streak / cooldown state machine (pure-ish; reads + writes registry)
# ---------------------------------------------------------------------------


def _update_streak_locked(agent: dict, subagent_count: int) -> int:
    """Increment / reset the idle streak on ``agent`` and return new value.

    Called while holding ``hub.registry._lock`` from :func:`check_agent_auto_dispatch`.
    """
    prev_streak = int(agent.get("idle_streak") or 0)
    if subagent_count == 0:
        new_streak = prev_streak + 1
    else:
        new_streak = 0
    agent["idle_streak"] = new_streak
    return new_streak


def _cooldown_active_locked(agent: dict, now: float, cooldown_s: int) -> bool:
    """Return True if the per-head cooldown window hasn't expired yet."""
    last_fire = agent.get("auto_dispatch_last_fire_ts")
    if not last_fire:
        return False
    try:
        elapsed = now - float(last_fire)
    except (TypeError, ValueError):
        return False
    return elapsed < cooldown_s


# ---------------------------------------------------------------------------
# Fire-and-forget dispatch bridge (sync/async agnostic)
# ---------------------------------------------------------------------------


def _in_async_context() -> bool:
    """Return True iff called from a thread with a running asyncio event loop.

    The heartbeat path reaches ``check_agent_auto_dispatch`` from both
    sync Django views (``POST /api/agents/register/``) and the async WS
    consumer (``handle_heartbeat`` in ``hub/consumers/_agent_handlers.py``).
    Django 4.1+ refuses ORM calls from an async context —
    ``SynchronousOnlyOperation`` is raised. Detecting which side we're
    on lets us keep the sync call cheap while moving WS-triggered fires
    to a thread where ORM is legal.
    """
    try:
        import asyncio

        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _dispatch_in_thread(
    agent_name: str, workspace_id: int, text: str, metadata: dict
) -> Optional[int]:
    """Run ``_post_dispatch_message`` in the appropriate execution context.

    If called from a sync context (Django view, management command,
    tests), run inline and return the resulting message id so
    existing callers / tests keep their synchronous observable
    behaviour.

    If called from an async context (the WS ``handle_heartbeat`` path),
    delegate to a daemon thread so Django ORM runs in a sync context
    and does not raise ``SynchronousOnlyOperation``. The thread is
    fire-and-forget — the heartbeat hot path returns immediately and
    the returned id is ``None`` because the insert is in flight. The
    thread's own exception handling (inside ``_post_dispatch_message``)
    still logs on failure.
    """
    if not _in_async_context():
        return _post_dispatch_message(agent_name, workspace_id, text, metadata)
    try:
        t = threading.Thread(
            target=_post_dispatch_message,
            args=(agent_name, workspace_id, text, metadata),
            name=f"auto-dispatch-{agent_name}",
            daemon=True,
        )
        t.start()
    except Exception:  # noqa: BLE001 — heartbeat hot path must not raise
        log.exception(
            "auto_dispatch: failed to spawn dispatch thread for %s", agent_name
        )
        return None
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_agent_auto_dispatch(agent_name: str) -> Optional[dict]:
    """Run the auto-dispatch state machine for one agent, based on registry state.

    Called from ``hub/registry/_heartbeat.py::update_heartbeat`` on the
    heartbeat hot path. Returns a dict summarizing what happened (for
    observability / tests), or ``None`` when nothing fired.

    Best-effort — any exception is logged and swallowed. The heartbeat
    path must never fail because of auto-dispatch.
    """
    try:
        if _is_disabled():
            return None

        host = _head_host_from_name(agent_name)
        if host is None:
            return None
        lane = LANE_FOR_HOST.get(host)
        if not lane:
            return None

        # Deferred import to avoid a circular: hub.registry is the caller.
        from hub.registry import _agents, _lock

        threshold = _streak_threshold()
        cooldown_s = _cooldown_seconds()
        now = time.time()

        with _lock:
            agent = _agents.get(agent_name)
            if not agent:
                return None
            subagent_count = int(agent.get("subagent_count") or 0)
            streak = _update_streak_locked(agent, subagent_count)
            if subagent_count > 0:
                return {"decision": "reset", "streak": 0}
            if streak < threshold:
                return {"decision": "streak_increment", "streak": streak}
            if _cooldown_active_locked(agent, now, cooldown_s):
                return {"decision": "cooldown_skip", "streak": streak}
            workspace_id = agent.get("workspace_id")
            # Arm cooldown + reset streak optimistically so a reentrant
            # call (unlikely but possible under asgiref) doesn't fire twice.
            agent["auto_dispatch_last_fire_ts"] = now
            agent["idle_streak"] = 0

        # Everything below runs without the registry lock.
        if workspace_id is None:
            log.warning("auto_dispatch: %s has no workspace_id — skip", agent_name)
            return {"decision": "no_workspace", "streak": streak}

        pick = _run_pick_todo(lane)
        text = _compose_dispatch_text(streak, pick, cooldown_s)
        metadata = {
            "kind": "auto-dispatch",
            "agent": agent_name,
            "lane": lane,
            "streak": streak,
            "todo_number": (pick or {}).get("number"),
            "todo_title": (pick or {}).get("title"),
        }
        # The heartbeat hot path may be called from either a sync view
        # (``/api/agents/register/``) or the async WS consumer
        # (``handle_heartbeat`` in ``hub/consumers/_agent_handlers.py``).
        # ``_post_dispatch_message`` performs Django ORM work which
        # Django 4.1+ refuses to run from an async context, raising
        # ``SynchronousOnlyOperation``. That exception was being caught
        # and logged but meant no auto-dispatch DM was ever delivered
        # through the WS path. Offload to a worker thread so the ORM
        # runs in a sync context regardless of where the heartbeat
        # came from. Fire-and-forget matches the "best-effort" contract
        # of this whole module — the caller never awaited the result.
        msg_id = _dispatch_in_thread(
            agent_name, int(workspace_id), text, metadata
        )
        log.info(
            "auto_dispatch: fired agent=%s lane=%s streak=%d todo=%s msg=%s",
            agent_name,
            lane,
            streak,
            (pick or {}).get("number"),
            msg_id,
        )
        return {
            "decision": "fired",
            "streak": streak,
            "lane": lane,
            "pick": pick,
            "message_id": msg_id,
        }
    except Exception:
        log.exception("auto_dispatch: check_agent_auto_dispatch failed for %s", agent_name)
        return None


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _reset_auto_dispatch_state_for_tests(agent_name: Optional[str] = None) -> None:
    """Clear per-agent streak / cooldown state. Test-only utility.

    ``None`` clears every head-* entry; a specific name clears just that
    one.
    """
    from hub.registry import _agents, _lock

    with _lock:
        targets = (
            [agent_name] if agent_name is not None else list(_agents.keys())
        )
        for name in targets:
            a = _agents.get(name)
            if not a:
                continue
            a.pop("idle_streak", None)
            a.pop("auto_dispatch_last_fire_ts", None)
