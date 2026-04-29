"""Cross-channel @mention push notifications (msg#15767).

When a chat message contains ``@<principal>`` tokens, fan out a DM
notification to each mentioned principal — even if they are not
subscribed to the source channel. "Push" is implemented as a regular
:class:`Message` row inserted into the canonical
``dm:<sender>|<target>`` channel, lazy-created via
:func:`hub.views.api._ensure_dm_channel` and broadcast on the channel
layer. The DM notification carries a ``metadata["kind"]="mention-push"``
marker so the UI can style it distinctly if it wishes.

Public surface (imported by
``hub/consumers/_agent_message.py``,
``hub/consumers/_dashboard_message.py``, and
``hub/views/api/_messages.py``):

  - :func:`parse_mention_tokens` — pure-function @token scanner.
  - :func:`resolve_mention_targets` — expand tokens into usernames.
  - :func:`expand_mentions_and_notify` — scan + fan-out + persist + broadcast.

Grammar (see spec in PR body):

  * ``@<name>`` must be preceded by start-of-message, whitespace, or
    non-identifier punctuation (``,.;:!?()[]{}<>`` etc.). An ``@``
    adjacent to a word character on its left is NOT a mention, which
    rules out ``foo@example.com`` and ``https://user@host``.
  * ``<name>`` is one or more of ``[A-Za-z0-9._-]``; trailing ``.``
    (e.g. sentence-final) is stripped.
  * Group tokens: ``all``, ``agents``, ``heads``, ``healers``,
    ``managers``, ``workers``, ``mambas`` (the last preserved for
    legacy fleet compatibility).

Rate limit: ``@all`` expansions are capped per sender per minute via
``SCITEX_OROCHI_MENTION_ALL_RATE_LIMIT_PER_MIN`` (default 3). The counter
is in-process — a hub restart resets it, which is acceptable because
the cap's only purpose is to throttle a single runaway agent loop.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Iterable

log = logging.getLogger("orochi.mentions")

# ---------------------------------------------------------------------------
# Token parser
# ---------------------------------------------------------------------------

# ``@name`` scanner. ``(?<![\w@])`` forbids a word char OR a second ``@``
# (the ``??`` in URLs like ``git@github.com`` is ruled out by ``\w``
# already, but ``foo@@bar`` should also not double-fire). The name body
# allows letters, digits, dots, underscores, hyphens. Trailing ``.``
# (sentence-final) is stripped in post-processing.
_MENTION_RE = re.compile(r"(?<![\w@.])@([A-Za-z0-9][\w.\-]*)")

# Group tokens the hub knows how to expand. Each maps to a predicate
# over ``User.username``; see :func:`resolve_mention_targets`. ``mambas``
# is kept for backwards compatibility with the legacy fleet roster
# established in ``hub/consumers/_dashboard_message.py``.
_GROUP_PATTERNS: dict[str, object] = {
    "all": lambda username: True,
    "agents": lambda username: username.startswith("agent-"),
    "heads": lambda username: username.startswith("agent-head-"),
    "healers": lambda username: username.startswith("agent-healer-")
    or username.startswith("agent-mamba-healer-"),
    "managers": lambda username: username.startswith("agent-mgr-"),
    "workers": lambda username: username.startswith("agent-worker-"),
    "mambas": lambda username: username.startswith("agent-mamba-"),
}


def parse_mention_tokens(text: str) -> list[str]:
    """Return the ordered list of raw mention tokens found in ``text``.

    Tokens are lower-cased to match group-token keys case-insensitively,
    but the caller is expected to preserve the original-case copy for
    echo (the backend never auto-corrects the user's spelling).

    Deduplication is intentionally NOT done here — the caller decides
    whether to dedupe, because group mentions expand into distinct
    usernames and the right place to dedupe is after expansion.

    Examples::

        >>> parse_mention_tokens("hi @head-mba and @worker-bee")
        ['head-mba', 'worker-bee']
        >>> parse_mention_tokens("reach me at foo@example.com")
        []
        >>> parse_mention_tokens("@ALL please check in")
        ['all']
    """
    if not text:
        return []
    raw = _MENTION_RE.findall(text)
    cleaned: list[str] = []
    for token in raw:
        # Strip trailing punctuation that the regex happens to consume
        # (our body class allows ``.`` and ``-`` so ``@alice.`` keeps
        # the dot; sentence-final dots should not be part of the name).
        token = token.rstrip(".-_")
        if not token:
            continue
        cleaned.append(token.lower())
    return cleaned


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def resolve_mention_targets(
    workspace_id: int,
    tokens: Iterable[str],
    *,
    exclude_usernames: Iterable[str] = (),
) -> list[str]:
    """Expand mention tokens into a deduped, ordered list of Django usernames.

    For each token in ``tokens``:

      * If it's a known group token (``all``, ``agents``, ``heads``,
        ``healers``, ``managers``, ``workers``, ``mambas``), iterate
        over every :class:`WorkspaceMember` in the workspace and include
        usernames matching the group's predicate.
      * Otherwise, treat the token as a single-principal reference:
        try ``agent-<token>`` first (canonical agent username), then
        fall back to a bare ``<token>`` match against ``User.username``.

    Usernames in ``exclude_usernames`` (typically the sender) are
    dropped to avoid self-notification. The final list preserves
    first-occurrence order so downstream DM threading is deterministic.
    """
    # Imports are local so this module can be imported at startup
    # without dragging in Django model loading (unit tests that just
    # hit the parser shouldn't need the ORM).
    from django.contrib.auth.models import User

    from hub.models import WorkspaceMember

    tokens = list(tokens)
    if not tokens:
        return []

    excluded = {u for u in exclude_usernames if u}
    result: list[str] = []
    seen: set[str] = set()

    # Build the workspace-member username pool once; used by both the
    # group-expansion branch and the fallback bare-name lookup.
    member_usernames: list[str] = list(
        WorkspaceMember.objects.filter(workspace_id=workspace_id)
        .values_list("user__username", flat=True)
    )

    def _add(username: str) -> None:
        if not username or username in excluded or username in seen:
            return
        seen.add(username)
        result.append(username)

    for token in tokens:
        key = token.lower()
        if key in _GROUP_PATTERNS:
            predicate = _GROUP_PATTERNS[key]
            for uname in member_usernames:
                if predicate(uname):
                    _add(uname)
            continue

        # Single-principal lookup. Prefer the synthetic agent-user
        # (``agent-<name>``) because that's the canonical form agents
        # register under; fall back to a bare match for humans.
        agent_username = f"agent-{token}"
        if agent_username in member_usernames:
            _add(agent_username)
            continue
        if token in member_usernames:
            _add(token)
            continue
        # Last resort: probe the User table outside the workspace
        # pool so cross-workspace logins we haven't cached locally
        # still resolve — but only if the user exists to avoid
        # creating ghost DMs to non-existent principals.
        if User.objects.filter(username=agent_username).exists():
            _add(agent_username)
            continue
        if User.objects.filter(username=token).exists():
            _add(token)
            continue
        # Channel-name mention: @general → all subscribers of #general.
        # Normalise to #token and look up ChannelMembership rows so that
        # ``@general`` pings everyone subscribed to #general. Fail-soft:
        # unrecognised tokens are silently skipped (same as before).
        from hub.models import Channel, ChannelMembership

        ch_name = f"#{token}" if not token.startswith("#") else token
        try:
            ch = Channel.objects.get(workspace_id=workspace_id, name=ch_name)
            for uname in (
                ChannelMembership.objects.filter(channel=ch)
                .values_list("user__username", flat=True)
            ):
                _add(uname)
        except Channel.DoesNotExist:
            pass

    return result


# ---------------------------------------------------------------------------
# Rate limit for @all
# ---------------------------------------------------------------------------


def _rate_limit_setting() -> int:
    """Return the per-sender @all cap per 60s window (env-configurable)."""
    raw = os.environ.get("SCITEX_OROCHI_MENTION_ALL_RATE_LIMIT_PER_MIN", "3")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 3
    return max(value, 0)


_rate_lock = threading.Lock()
# Per-sender ring of recent @all send timestamps (unix seconds).
_rate_events: dict[str, list[float]] = {}
_RATE_WINDOW_S = 60.0


def _consume_all_rate_token(sender_username: str) -> bool:
    """Return True if the sender may fire an ``@all`` right now.

    Sliding-window counter: keep only timestamps inside the last 60s,
    allow up to ``_rate_limit_setting()`` per window. When a call is
    denied, log the suppression so operators can tune the cap.
    """
    cap = _rate_limit_setting()
    if cap <= 0:
        return False
    now = time.time()
    with _rate_lock:
        bucket = _rate_events.setdefault(sender_username, [])
        # Drop stale entries.
        bucket[:] = [t for t in bucket if now - t < _RATE_WINDOW_S]
        if len(bucket) >= cap:
            return False
        bucket.append(now)
    return True


def _reset_rate_limit_for_tests() -> None:
    """Test helper — clears the in-process rate-limit window."""
    with _rate_lock:
        _rate_events.clear()


# ---------------------------------------------------------------------------
# Fan-out
# ---------------------------------------------------------------------------


def _principal_key_for_username(username: str) -> str:
    """Return ``agent:<name>`` for synthetic agent users, else ``human:<name>``."""
    if username.startswith("agent-"):
        return f"agent:{username[len('agent-'):]}"
    return f"human:{username}"


def _canonical_dm_name(a_username: str, b_username: str) -> str:
    """Build the ``dm:<a>|<b>`` canonical channel name for a pair of users."""
    keys = sorted(
        [_principal_key_for_username(a_username), _principal_key_for_username(b_username)]
    )
    return "dm:" + "|".join(keys)


def expand_mentions_and_notify(
    *,
    workspace_id: int,
    source_channel: str,
    source_msg_id: int | None,
    sender_username: str,
    text: str,
) -> list[dict]:
    """Parse mentions in ``text`` and fan out DM notifications.

    Called synchronously from the message-persistence paths (WS agent,
    WS dashboard, REST ``api_messages``). Returns the list of
    notification records that were created (``[{"recipient": ..., "dm":
    ..., "message_id": ...}, ...]``) for logging/inspection; the caller
    is free to ignore the return value.

    Side effects:

      1. ``_ensure_dm_channel`` lazy-creates each
         ``dm:<sender>|<target>`` channel + participants.
      2. A :class:`Message` row is inserted into that DM channel with
         ``metadata["kind"]="mention-push"``, ``source_channel``, and
         ``source_msg_id`` set.
      3. The message is broadcast on the DM channel group so any
         already-connected recipient dashboard / MCP receives it in
         real time.

    Skipped when:

      * There are no mention tokens.
      * ``source_channel`` is already a DM (don't cross-notify within
        private threads; the source DM already pushes to participants).
      * A resolved target already has a ``ChannelMembership`` row on
        the source channel — the normal channel fanout already reaches
        them, so adding a DM would be duplicate noise.
      * The target is the sender themselves.

    ``@all`` expansions above the rate-limit are dropped with a log
    line; other mentions in the same message still go through.
    """
    if not text:
        return []
    if source_channel and source_channel.startswith("dm:"):
        # Mentions inside DMs don't need cross-channel push — the DM
        # already hits the participants directly. Re-fanning would
        # create a recursive notification loop between the same pair.
        return []

    raw_tokens = parse_mention_tokens(text)
    if not raw_tokens:
        return []

    # ``@all`` rate limit — per sender, 60s window.
    heavy_tokens = {"all"}
    dropped_heavy: list[str] = []
    effective_tokens: list[str] = []
    for tok in raw_tokens:
        if tok in heavy_tokens:
            if _consume_all_rate_token(sender_username):
                effective_tokens.append(tok)
            else:
                dropped_heavy.append(tok)
        else:
            effective_tokens.append(tok)
    if dropped_heavy:
        log.warning(
            "mention-push: rate-limited @%s from %s (window=%ds, cap=%d)",
            dropped_heavy[0],
            sender_username,
            int(_RATE_WINDOW_S),
            _rate_limit_setting(),
        )

    if not effective_tokens:
        return []

    # Local imports so parser/rate-limit can be unit-tested without
    # the full Django app context.
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    from hub.consumers import _sanitize_group
    from hub.models import Channel, ChannelMembership, Message, Workspace
    from hub.views.api._dms import _ensure_dm_channel

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        log.warning("mention-push: workspace %s missing", workspace_id)
        return []

    targets = resolve_mention_targets(
        workspace_id=workspace_id,
        tokens=effective_tokens,
        exclude_usernames=[sender_username],
    )
    if not targets:
        return []

    # Fetch the source channel once so we can query memberships in one
    # SQL roundtrip. Missing row => no existing subscribers, proceed.
    try:
        src_channel = Channel.objects.get(
            workspace=workspace, name=source_channel
        )
    except Channel.DoesNotExist:
        src_channel = None

    subscriber_usernames: set[str] = set()
    if src_channel is not None:
        subscriber_usernames = set(
            ChannelMembership.objects.filter(channel=src_channel)
            .values_list("user__username", flat=True)
        )

    layer = get_channel_layer()
    notifications: list[dict] = []
    for target_username in targets:
        # Recipient already subscribed — existing fanout reaches them.
        if target_username in subscriber_usernames:
            continue

        dm_name = _canonical_dm_name(sender_username, target_username)
        try:
            dm_channel = _ensure_dm_channel(workspace, dm_name)
        except Exception:
            log.exception("mention-push: _ensure_dm_channel failed for %s", dm_name)
            continue
        if dm_channel is None:
            log.warning(
                "mention-push: could not resolve DM channel %s (sender=%s, target=%s)",
                dm_name,
                sender_username,
                target_username,
            )
            continue

        # Derive sender_type from the username shape — synthetic agent
        # users carry the ``agent-`` prefix.
        sender_type = "agent" if sender_username.startswith("agent-") else "human"
        metadata = {
            "kind": "mention-push",
            "source_channel": source_channel,
            "source_msg_id": source_msg_id,
            "mentioned": target_username,
        }
        try:
            dm_msg = Message.objects.create(
                workspace=workspace,
                channel=dm_channel,
                sender=sender_username,
                sender_type=sender_type,
                content=text,
                metadata=metadata,
            )
        except Exception:
            log.exception(
                "mention-push: Message.create failed dm=%s sender=%s target=%s",
                dm_name,
                sender_username,
                target_username,
            )
            continue

        # Broadcast on the DM channel group so any already-connected
        # recipient socket delivers it live. Best-effort — a broken
        # channel layer must not fail the parent write.
        if layer is not None:
            group = _sanitize_group(f"channel_{workspace.id}_{dm_name}")
            try:
                async_to_sync(layer.group_send)(
                    group,
                    {
                        "type": "chat.message",
                        "id": dm_msg.id,
                        "sender": sender_username,
                        "sender_type": sender_type,
                        "channel": dm_name,
                        "kind": "dm",
                        "text": text,
                        "ts": dm_msg.ts.isoformat(),
                        "metadata": metadata,
                    },
                )
            except Exception:
                log.exception("mention-push: group_send failed for %s", dm_name)

        # Fire PWA web push so ywatanabe gets an active notification even
        # when the app tab is closed (todo#308). Best-effort — never blocks.
        try:
            from hub.push import send_push_to_subscribers_async

            send_push_to_subscribers_async(
                workspace_id=workspace.id,
                channel=dm_name,
                sender=sender_username,
                text=text,
                message_id=dm_msg.id,
            )
        except Exception:
            log.debug("mention-push: web push skipped for %s", target_username)

        notifications.append(
            {
                "recipient": target_username,
                "dm": dm_name,
                "message_id": dm_msg.id,
            }
        )

    return notifications
