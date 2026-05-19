"""Identity + cardinality-enforce helpers for :class:`AgentConsumer`.

Lead-state-handover (ZOO#12) — FR-C / FR-E.

The connect path for ``hub/consumers/_agent.py`` is dense enough already
(see scitex-orochi#255 singleton enforcement); pushing the new
UUID-based identity stamping and the generic
``cardinality_enforced_at_hub`` guard out into this module keeps the
consumer file under the 512-line cap that the package convention
enforces.

The pieces here are deliberately split into:

  - :func:`parse_identity_query` — pure parsing of ``?instance_uuid=``,
    ``?cardinality_enforce=`` and ``?failback_grace=`` from the WS
    query string. Returns a small dataclass-ish dict so callers stay
    explicit about which knob is being read.

  - :func:`active_session_with_different_uuid` — DB lookup that
    powers the cardinality-enforce 4001 reject path. Sync, run via
    ``database_sync_to_async`` from the consumer.

  - :func:`record_session_open` / :func:`record_session_close` —
    AgentSession row lifecycle so the connect / disconnect paths
    don't have to know the model fields.

The design notes for the layered enforcement (4001 vs the existing
4409) are duplicated near each call-site so a future reader doesn't
have to chase them through multiple files.
"""

from __future__ import annotations

import os
import uuid
from typing import Optional, TypedDict


class IdentityQuery(TypedDict, total=False):
    """Parsed identity-related query params from the WS connect URL."""

    instance_uuid: str
    cardinality_enforce: bool
    failback_grace: bool
    hostname: str
    pid: Optional[int]


def _is_uuid4(candidate: str) -> bool:
    """Return True iff ``candidate`` is a syntactically valid uuid4 string.

    We accept any RFC-4122 UUID rather than strictly version=4 so that
    a future migration to uuid7 (time-ordered) doesn't reject existing
    clients. The mission spec calls out uuid4 by name, but the
    server-side semantics only require global uniqueness + 36-char
    canonical form, and ``uuid.UUID`` validates that.
    """
    if not candidate:
        return False
    try:
        uuid.UUID(candidate)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def parse_identity_query(qs) -> IdentityQuery:
    """Pull instance_uuid + cardinality + failback knobs from a parsed qs.

    ``qs`` is the dict returned by :func:`urllib.parse.parse_qs` (lists
    of values per key). Missing fields stay absent; legacy clients
    without ``instance_uuid`` fall through to permissive behaviour with
    a logged warning at the call-site.
    """
    out: IdentityQuery = {}
    raw_uuid = (qs.get("instance_uuid") or [""])[0] or ""
    if raw_uuid and _is_uuid4(raw_uuid):
        out["instance_uuid"] = raw_uuid
    elif raw_uuid:
        # Caller decides how loud to be — we just don't put bad input
        # into the typed bucket.
        out["instance_uuid"] = ""

    flag_raw = (qs.get("cardinality_enforce") or [""])[0] or ""
    out["cardinality_enforce"] = flag_raw.lower() in ("1", "true", "yes")

    grace_raw = (qs.get("failback_grace") or [""])[0] or ""
    out["failback_grace"] = grace_raw.lower() in ("1", "true", "yes")

    out["hostname"] = (qs.get("hostname") or [""])[0] or ""
    pid_raw = (qs.get("pid") or [""])[0] or ""
    try:
        out["pid"] = int(pid_raw) if pid_raw else None
    except (TypeError, ValueError):
        out["pid"] = None
    return out


def active_session_with_different_uuid(
    workspace_id: int, agent_name: str, instance_uuid: str
) -> bool:
    """True iff an AgentSession with same name + DIFFERENT uuid is still live.

    "Live" = ``disconnected_at IS NULL``. Used for FR-C: when the new
    connect's ``cardinality_enforce`` is true (or the existing live
    session's was), and there's an alive sibling under a different
    UUID, the newcomer must be rejected with code 4001 (unless
    ``?failback_grace=true``).
    """
    from hub.models import AgentSession

    qs = AgentSession.objects.filter(
        workspace_id=workspace_id,
        agent_name=agent_name,
        disconnected_at__isnull=True,
    )
    if instance_uuid:
        qs = qs.exclude(instance_uuid=instance_uuid)
    return qs.exists()


def any_active_session_enforces_cardinality(
    workspace_id: int, agent_name: str
) -> bool:
    """True iff any currently-alive session for this agent has the flag.

    The hub treats ``cardinality_enforced_at_hub`` as a sticky property
    of the agent name within a workspace: once any client has connected
    declaring the flag, subsequent newcomers are subject to the 4001
    guard regardless of what they themselves claim. This blocks the
    trivial bypass where a malicious / buggy second instance simply
    omits ``?cardinality_enforce=true`` to dodge enforcement.
    """
    from hub.models import AgentSession

    return AgentSession.objects.filter(
        workspace_id=workspace_id,
        agent_name=agent_name,
        disconnected_at__isnull=True,
        cardinality_enforced=True,
    ).exists()


def record_session_open(
    workspace_id: int,
    agent_name: str,
    instance_uuid: str,
    hostname: str,
    pid: Optional[int],
    ws_session_id: str,
    cardinality_enforced: bool,
):
    """Upsert an AgentSession row for this connect.

    Returns the saved AgentSession instance. ``instance_uuid`` is the
    natural unique key so a reconnect with the same UUID (e.g. the WS
    transport flapped) updates the live row instead of creating a
    duplicate. ``disconnected_at`` is cleared on upsert so a
    flap-then-reconnect doesn't leave the session in a stale closed
    state.
    """
    from hub.models import AgentSession

    if not instance_uuid:
        # Legacy path — no row to write. The WS connect still works but
        # the dashboard's "agent_id" stamping on outbound messages will
        # fall back to the legacy ``<name>:<pid>`` form documented at
        # the consumer call-site.
        return None
    sess, _ = AgentSession.objects.update_or_create(
        instance_uuid=instance_uuid,
        defaults={
            "workspace_id": workspace_id,
            "agent_name": agent_name,
            "hostname": hostname or "",
            "pid": pid,
            "ws_session_id": ws_session_id or "",
            "cardinality_enforced": bool(cardinality_enforced),
            "disconnected_at": None,
        },
    )
    return sess


def record_session_close(instance_uuid: str) -> None:
    """Mark an AgentSession as disconnected. No-op for legacy clients."""
    if not instance_uuid:
        return
    from django.utils import timezone

    from hub.models import AgentSession

    AgentSession.objects.filter(instance_uuid=instance_uuid).update(
        disconnected_at=timezone.now()
    )


def short_uuid(instance_uuid: str, length: int = 4) -> str:
    """Return the first ``length`` hex chars of a uuid for short display.

    Mission spec calls for a short ``lead:8af3`` style stamp on the UI
    when there is no name conflict; on conflict the dashboard expands
    to the full uuid via the session-meta endpoint. This helper keeps
    the truncation logic in one place so the WS stamp + the dashboard
    render code can't drift.
    """
    if not instance_uuid:
        return ""
    cleaned = instance_uuid.replace("-", "")
    return cleaned[:length]


def format_agent_id(agent_name: str, instance_uuid: str) -> str:
    """Stamp form: ``<name>:<uuid>``. Used in outgoing message meta.

    The dashboard collapses to short form (``<name>:<prefix>``) at
    render time using :func:`short_uuid`; the wire form keeps the full
    UUID so a stamp from this hub is safe to compare across hosts /
    timezones / hub restarts.
    """
    if not instance_uuid:
        # Last-ditch fallback so legacy clients still get a stable
        # provenance stamp. ``os.getpid()`` here is the HUB pid (not
        # the agent's), which is intentional: with no UUID we can at
        # least say "this hub instance saw the message".
        return f"{agent_name}:hub-{os.getpid()}"
    return f"{agent_name}:{instance_uuid}"
