"""
Declarative channel ACL — loaded from channels.yaml, cached with TTL.

Usage:
    from hub.channel_acl import check_write_allowed

    if not check_write_allowed(sender="some-agent", channel="#ywatanabe"):
        # silently drop or return an error

Config file:
    Loaded from SCITEX_OROCHI_CHANNELS_YAML env var, or
    ~/.scitex/orochi/channels.yaml by default.

    If the file does not exist, all senders are allowed everywhere (permissive
    default, so existing deployments are not broken by adding this module).

YAML format (example):
    apiVersion: scitex-orochi/v1
    kind: ChannelPolicy
    spec:
      channels:
        - name: '#ywatanabe'
          write: ['mamba-todo-manager', 'ywatanabe', 'head-*']
        - name: '#agent'
          write: ['mamba-*', 'head-*']
        - name: '#general'
          write: ['*']

Pattern matching:
    '*'       — allow all senders
    'mamba-*' — prefix glob (trailing * only)
    'exact'   — exact string match
"""

from __future__ import annotations

import fnmatch
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60  # re-read config at most once per minute

_lock = threading.Lock()
_acl_data: dict[str, list[str]] = {}   # channel -> list of write patterns
_last_load: float = 0.0
_last_path: str = ""


def _default_config_path() -> str:
    path_env = os.environ.get("SCITEX_OROCHI_CHANNELS_YAML", "")
    if path_env:
        return path_env
    return str(Path.home() / ".scitex" / "orochi" / "channels.yaml")


def _load_yaml(path: str) -> dict[str, list[str]]:
    """Parse channels.yaml and return {channel_name: [write_patterns]}."""
    try:
        import yaml  # PyYAML, already in Django deps
    except ImportError:
        log.warning("[channel_acl] PyYAML not available, ACL disabled")
        return {}

    try:
        with open(path) as f:
            doc: Any = yaml.safe_load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("[channel_acl] failed to load %s: %s", path, exc)
        return {}

    if not isinstance(doc, dict):
        return {}

    spec = doc.get("spec") or {}
    channels_list = spec.get("channels") or []
    result: dict[str, list[str]] = {}
    for entry in channels_list:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        write = entry.get("write") or []
        if isinstance(write, str):
            write = [write]
        result[name] = [str(p) for p in write]
    return result


def _refresh_if_stale() -> None:
    global _acl_data, _last_load, _last_path

    path = _default_config_path()
    now = time.monotonic()
    with _lock:
        if now - _last_load < _CACHE_TTL_SECONDS and path == _last_path:
            return
        _acl_data = _load_yaml(path)
        _last_load = now
        _last_path = path
        if _acl_data:
            log.debug("[channel_acl] loaded %d channel rules from %s", len(_acl_data), path)


def _matches_pattern(sender: str, pattern: str) -> bool:
    """Return True if sender matches the ACL pattern."""
    if pattern == "*":
        return True
    # Support trailing-* glob (e.g. "mamba-*", "head-*")
    return fnmatch.fnmatch(sender, pattern)


def check_write_allowed(
    sender: str, channel: str, workspace_id: int | None = None
) -> bool:
    """Return True if sender is allowed to write to channel.

    If the config file does not exist or the channel has no ACL entry,
    returns True (permissive default).

    Spec v3 §3.2 — DM channels (name starts with ``dm:`` or model row
    has ``kind="dm"``) bypass the yaml ACL. They are allowed iff the
    sender's ``WorkspaceMember`` is a ``DMParticipant`` of the channel.
    When ``workspace_id`` is not supplied we cannot scope the lookup,
    so we fall back to the permissive path (preserves non-WS callers).
    """
    if channel.startswith("dm:"):
        return _check_dm_write_allowed(sender, channel, workspace_id)

    # Defensive DB check: a Channel row may exist with kind="dm" even
    # without a dm: prefix (should never happen post-spec v3 §9 Q5,
    # but we defend anyway).
    if workspace_id is not None:
        try:
            from hub.models import Channel as _Channel

            ch = _Channel.objects.filter(
                workspace_id=workspace_id, name=channel
            ).only("kind").first()
            if ch is not None and ch.kind == _Channel.KIND_DM:
                return _check_dm_write_allowed(sender, channel, workspace_id)
        except Exception:
            pass

    _refresh_if_stale()
    with _lock:
        if not _acl_data:
            return True  # no config — allow all
        patterns = _acl_data.get(channel)
    if patterns is None:
        return True  # channel not in config — allow
    return any(_matches_pattern(sender, p) for p in patterns)


def _check_dm_write_allowed(
    sender: str, channel: str, workspace_id: int | None
) -> bool:
    """Return True if ``sender`` is a DMParticipant of ``channel``.

    Matches either agent senders (synthetic ``agent-<sender>`` users,
    per ``hub/views/auth.py``) or human senders (bare username). The
    denormalized ``identity_name`` column is checked first (hot path)
    with a fall-through to ``member__user__username`` for cases where
    the sender string differs from the registered identity.
    """
    if workspace_id is None:
        return False
    try:
        from hub.models import Channel as _Channel
        from hub.models import DMParticipant as _DMParticipant
    except Exception:
        return False

    base_qs = _DMParticipant.objects.filter(
        channel__workspace_id=workspace_id,
        channel__name=channel,
        channel__kind=_Channel.KIND_DM,
    )
    if not base_qs.exists():
        # No such DM channel — deny to avoid silent allow.
        return False

    # Match on the denormalized identity name (fast path) OR via the
    # User.username FK join. Agent senders may be recorded either as
    # "mamba-foo" (identity_name) or "agent-mamba-foo" (User.username).
    if base_qs.filter(identity_name=sender).exists():
        return True
    if base_qs.filter(member__user__username=sender).exists():
        return True
    if base_qs.filter(member__user__username=f"agent-{sender}").exists():
        return True
    return False


def reload() -> int:
    """Force reload of ACL from disk. Returns number of channel rules loaded."""
    global _last_load
    with _lock:
        _last_load = 0.0  # invalidate cache
    _refresh_if_stale()
    with _lock:
        return len(_acl_data)
