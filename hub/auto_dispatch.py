"""Server-side auto-dispatch for idle ``head-*`` agents (Layer 1 redesign).

Replaces the client-side ``scripts/client/auto-dispatch-probe.sh`` daemon
(PR #320) with hub-side detection driven off the heartbeat hot path.

Design (lead msg#16388, ywatanabe msg#16380)
--------------------------------------------

On every heartbeat from a ``head-<host>`` agent:

1. Compare the newly written ``orochi_subagent_count`` with the prior reading
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
    """Per-head minimum gap between auto-dispatches, in seconds.

    Resolution order (first non-None wins):
      1. ``SCITEX_AUTO_DISPATCH_COOLDOWN_SECONDS`` env var — highest
         precedence so ``mock.patch.dict(os.environ, ...)`` in tests
         and short-lived shell overrides always take effect without
         re-importing Django settings.
      2. ``django.conf.settings.AUTO_DISPATCH_COOLDOWN_SECONDS`` — the
         canonical production override (msg#17078 lane A). Docker
         compose sets this via an env var at boot; the settings module
         reads it there, and this path is what production hits when no
         shell override is in scope.
      3. 900s (15min) — matches the figure the DM text advertises.
    """
    raw = os.environ.get("SCITEX_AUTO_DISPATCH_COOLDOWN_SECONDS")
    if raw is not None:
        try:
            return max(int(raw), 0)
        except (TypeError, ValueError):
            pass
    try:
        from django.conf import settings

        val = getattr(settings, "AUTO_DISPATCH_COOLDOWN_SECONDS", None)
        if val is not None:
            return max(int(val), 0)
    except Exception:
        pass
    return 900


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


#: Max length of the full DM body. Deliberately kept under 400 chars so
#: the downstream Web Push 200-char body cap (``hub/push.py``) and any
#: future dashboard preview truncator still leaves the concrete shell
#: command visible — the single most actionable element in the DM.
#: msg#17078 lane A.
MAX_DISPATCH_BODY_CHARS = 400


def _compose_dispatch_text(
    streak: int,
    pick: Optional[dict],
    cooldown_s: int,
    agent_name: Optional[str] = None,
) -> str:
    """Build the Claude-visible instruction text.

    msg#17078 lane A augments the original (lead msg#16388) template so
    the recipient agent has a concrete shell command plus a fallback
    pointer (mgr-todo MCP). Compression rules:

    - Drop the redundant "Pick a high-priority todo..." sentence that
      was visible in clipped previews but carried no command; the
      candidate line + ``gh issue list`` line subsume it.
    - Keep the whole body under :data:`MAX_DISPATCH_BODY_CHARS` so the
      Web Push 200-char body cap + any dashboard previewer does not
      clip the command line.
    - ``gh`` command is tailored per recipient via ``agent_name`` (head
      name ends in ``-<host>``). When ``agent_name`` is None (legacy
      callers) the command falls back to the generic ``-<host>`` form.
    """
    cooldown_min = max(cooldown_s // 60, 1)
    host = _head_host_from_name(agent_name or "") or "<host>"
    if pick is None:
        candidate = "no open todo matched lane — pick from backlog or ask mgr-todo"
    else:
        title = (pick.get("title") or "").strip()
        # Hard-cap the title so a 200-char runaway issue title can't
        # alone blow past MAX_DISPATCH_BODY_CHARS.
        if len(title) > 80:
            title = title[:77] + "..."
        candidate = f"todo#{pick['number']} — {title}"
    cmd = (
        f"gh issue list --repo ywatanabe1989/scitex-orochi "
        f"--label ready-for-head-{host} --state open --limit 10"
    )
    text = (
        f"[auto-dispatch] idle {streak} cycles. Candidate: {candidate}. "
        f"Run: {cmd} — or DM mgr-todo for a pick. "
        f"Cooldown {cooldown_min}min."
    )
    # Hard belt-and-braces cap. The earlier title truncation should
    # already guarantee we stay inside MAX_DISPATCH_BODY_CHARS, but a
    # miscount in the template is a silent truncation bug — pin it.
    if len(text) > MAX_DISPATCH_BODY_CHARS:
        text = text[: MAX_DISPATCH_BODY_CHARS - 1].rstrip() + "…"
    return text


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

        # msg#17078 lane A — write-through the cooldown timestamp to
        # ``AgentProfile.last_auto_dispatch_at`` so the 15min window
        # survives hub restarts. Best-effort: the Message above is the
        # user-visible side effect; a failure here at worst lets the
        # next hub restart re-fire, which is the current (pre-fix)
        # behaviour.
        try:
            _persist_last_auto_dispatch_at(
                workspace_id, agent_name, time.time()
            )
        except Exception:  # pragma: no cover
            log.exception(
                "auto_dispatch: persist_last_auto_dispatch_at failed for %s",
                agent_name,
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
# Streak / cooldown state orochi_machine (pure-ish; reads + writes registry)
# ---------------------------------------------------------------------------


def _update_streak_locked(agent: dict, orochi_subagent_count: int) -> int:
    """Increment / reset the idle streak on ``agent`` and return new value.

    Called while holding ``hub.registry._lock`` from :func:`check_agent_auto_dispatch`.
    """
    prev_streak = int(agent.get("idle_streak") or 0)
    if orochi_subagent_count == 0:
        new_streak = prev_streak + 1
    else:
        new_streak = 0
    agent["idle_streak"] = new_streak
    return new_streak


def _cooldown_active_locked(agent: dict, now: float, cooldown_s: int) -> bool:
    """Return True if the per-head cooldown window hasn't expired yet.

    Reads only the in-memory ``auto_dispatch_last_fire_ts`` slot. The
    slot is hydrated from ``AgentProfile.last_auto_dispatch_at`` by
    :func:`_hydrate_cooldown_from_db_locked` on first lookup so the
    window survives hub restarts (msg#17078 lane A).
    """
    last_fire = agent.get("auto_dispatch_last_fire_ts")
    if not last_fire:
        return False
    try:
        elapsed = now - float(last_fire)
    except (TypeError, ValueError):
        return False
    return elapsed < cooldown_s


# ---------------------------------------------------------------------------
# DB-persisted cooldown (msg#17078 lane A)
#
# Before this section existed, ``auto_dispatch_last_fire_ts`` lived only in
# the in-memory ``hub.registry._agents[<name>]`` dict. A hub restart wiped
# the dict and the next heartbeat would re-fire an auto-dispatch within
# one streak-threshold cycle (~1-5min) even though the DM text advertised
# a 15min cooldown — 8 DMs observed to head-mba in 40min in the incident
# report. Promoting the timestamp to ``AgentProfile.last_auto_dispatch_at``
# makes the window honest across restarts.
# ---------------------------------------------------------------------------


def _read_last_auto_dispatch_at_from_db(
    workspace_id: int, agent_name: str
) -> Optional[float]:
    """Return the DB-stored last-fire timestamp as a unix float, or None.

    Any exception (DB down, migration not yet applied, AgentProfile row
    absent) yields ``None`` — auto-dispatch is best-effort and the
    heartbeat hot path must never fail here.
    """
    try:
        from hub.models import AgentProfile

        row = AgentProfile.objects.filter(
            workspace_id=workspace_id, name=agent_name
        ).only("last_auto_dispatch_at").first()
        if row is None:
            return None
        ts = row.last_auto_dispatch_at
        if ts is None:
            return None
        return ts.timestamp()
    except Exception:  # pragma: no cover — belt-and-braces
        log.debug(
            "auto_dispatch: _read_last_auto_dispatch_at_from_db failed for %s",
            agent_name,
            exc_info=True,
        )
        return None


def _persist_last_auto_dispatch_at(
    workspace_id: int, agent_name: str, now: float
) -> None:
    """Upsert ``AgentProfile.last_auto_dispatch_at = now`` for the agent.

    Called from :func:`_post_dispatch_message` which already runs on a
    sync thread when the heartbeat arrived on the asyncio loop, so
    ``update_or_create`` is safe to call here directly.
    """
    try:
        from datetime import datetime, timezone

        from hub.models import AgentProfile

        AgentProfile.objects.update_or_create(
            workspace_id=workspace_id,
            name=agent_name,
            defaults={
                "last_auto_dispatch_at": datetime.fromtimestamp(now, tz=timezone.utc),
            },
        )
    except Exception:  # pragma: no cover — belt-and-braces
        log.exception(
            "auto_dispatch: _persist_last_auto_dispatch_at failed for %s",
            agent_name,
        )


def _hydrate_cooldown_from_db_locked(
    agent: dict, workspace_id: Optional[int], agent_name: str
) -> None:
    """Ensure ``agent["auto_dispatch_last_fire_ts"]`` reflects the DB.

    Called under ``hub.registry._lock``. The ``_hydrated`` sentinel lets
    us limit DB roundtrips to one per agent per hub lifetime (the happy
    path is in-memory only thereafter — the write-through path keeps
    the slot synced after each fire).

    If we're running under the asyncio event loop (WS handler calls
    ``handle_heartbeat`` → ``update_heartbeat`` → here), Django ORM
    would raise ``SynchronousOnlyOperation``. We guard with
    :func:`_in_async_context` and, in the async case, defer hydration
    to a worker thread that writes back into the same in-memory slot
    — on the very next heartbeat the cooldown check sees the hydrated
    value. The cost is that the first post-restart heartbeat after a
    fire *could* fire again before hydration lands; we accept that vs
    the alternative of blocking the WS loop on a DB query.
    """
    if agent.get("auto_dispatch_hydrated"):
        return
    if workspace_id is None:
        return
    if _in_async_context():
        # Defer to a worker thread — re-acquire the lock inside to
        # write. Only schedule one hydrate per agent.
        agent["auto_dispatch_hydrated"] = True

        def _bg_hydrate():
            ts = _read_last_auto_dispatch_at_from_db(workspace_id, agent_name)
            if ts is None:
                return
            try:
                from hub.registry import _agents as _a
                from hub.registry import _lock as _l

                with _l:
                    row = _a.get(agent_name)
                    if row is not None and not row.get(
                        "auto_dispatch_last_fire_ts"
                    ):
                        row["auto_dispatch_last_fire_ts"] = ts
            except Exception:  # pragma: no cover
                log.debug(
                    "auto_dispatch: _bg_hydrate failed for %s",
                    agent_name,
                    exc_info=True,
                )

        try:
            threading.Thread(
                target=_bg_hydrate,
                name=f"auto-dispatch-hydrate-{agent_name}",
                daemon=True,
            ).start()
        except Exception:  # pragma: no cover
            log.debug(
                "auto_dispatch: could not spawn hydrate thread for %s",
                agent_name,
                exc_info=True,
            )
        return
    # Sync context — do the read inline.
    ts = _read_last_auto_dispatch_at_from_db(workspace_id, agent_name)
    agent["auto_dispatch_hydrated"] = True
    if ts is not None and not agent.get("auto_dispatch_last_fire_ts"):
        agent["auto_dispatch_last_fire_ts"] = ts


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
    """Run the auto-dispatch state orochi_machine for one agent, based on registry state.

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
            orochi_subagent_count = int(agent.get("orochi_subagent_count") or 0)
            workspace_id = agent.get("workspace_id")
            # msg#17078 lane A — hydrate the in-memory cooldown from the
            # DB on first lookup so a hub restart cannot drop the window.
            _hydrate_cooldown_from_db_locked(agent, workspace_id, agent_name)
            streak = _update_streak_locked(agent, orochi_subagent_count)
            if orochi_subagent_count > 0:
                return {"decision": "reset", "streak": 0}
            if streak < threshold:
                return {"decision": "streak_increment", "streak": streak}
            if _cooldown_active_locked(agent, now, cooldown_s):
                # msg#17078 lane A: do NOT reset the streak here. Any
                # subsequent zero-reading tick within the cooldown
                # window must continue to return ``cooldown_skip``
                # rather than silently re-arming the state orochi_machine.
                return {"decision": "cooldown_skip", "streak": streak}
            # Arm cooldown + reset streak optimistically so a reentrant
            # call (unlikely but possible under asgiref) doesn't fire twice.
            agent["auto_dispatch_last_fire_ts"] = now
            agent["idle_streak"] = 0

        # Everything below runs without the registry lock.
        if workspace_id is None:
            log.warning("auto_dispatch: %s has no workspace_id — skip", agent_name)
            return {"decision": "no_workspace", "streak": streak}

        pick = _run_pick_todo(lane)
        text = _compose_dispatch_text(streak, pick, cooldown_s, agent_name)
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
    one. Also wipes the DB-persisted cooldown so test ordering is
    deterministic (msg#17078 lane A made the cooldown DB-backed; without
    clearing the column here a second test in the same process would
    see the prior test's last-fire row and hit ``cooldown_skip``).
    """
    from hub.registry import _agents, _lock

    names_to_reset: list[tuple[str, Optional[int]]] = []
    with _lock:
        targets = (
            [agent_name] if agent_name is not None else list(_agents.keys())
        )
        for name in targets:
            a = _agents.get(name)
            if not a:
                continue
            names_to_reset.append((name, a.get("workspace_id")))
            a.pop("idle_streak", None)
            a.pop("auto_dispatch_last_fire_ts", None)
            a.pop("auto_dispatch_hydrated", None)

    # Best-effort DB-side clear.
    try:
        from hub.models import AgentProfile

        for name, ws_id in names_to_reset:
            if ws_id is None:
                continue
            AgentProfile.objects.filter(
                workspace_id=ws_id, name=name
            ).update(last_auto_dispatch_at=None)
    except Exception:
        log.debug(
            "auto_dispatch: _reset_auto_dispatch_state_for_tests DB clear failed",
            exc_info=True,
        )
