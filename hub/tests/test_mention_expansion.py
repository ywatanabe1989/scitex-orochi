"""Tests for the cross-channel @mention push helper (``hub/mentions.py``).

Covers three layers:

  1. The pure-function :func:`parse_mention_tokens` — regex edge cases
     (email-like, URL-like, punctuation, dedupe, case).
  2. :func:`resolve_mention_targets` — group-token expansion, synthetic
     agent-user lookup, sender exclusion.
  3. :func:`expand_mentions_and_notify` — end-to-end fan-out: DM
     channel lazy-create, mention-push metadata marker, subscriber
     dedupe, rate-limit gate for ``@all``.

Uses Django's in-memory channels layer via ``CHANNEL_LAYERS`` override
so ``group_send`` calls don't fail.
"""

from __future__ import annotations

import os
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from hub.mentions import (
    _reset_rate_limit_for_tests,
    expand_mentions_and_notify,
    parse_mention_tokens,
    resolve_mention_targets,
)
from hub.models import (
    Channel,
    ChannelMembership,
    Message,
    Workspace,
    WorkspaceMember,
)


# ---------------------------------------------------------------------------
# 1. Parser
# ---------------------------------------------------------------------------


class ParseMentionTokensTest(TestCase):
    """The pure regex-based token scanner."""

    def test_single_username_mention(self):
        self.assertEqual(parse_mention_tokens("hi @alice"), ["alice"])

    def test_two_distinct_mentions(self):
        self.assertEqual(
            parse_mention_tokens("ping @alice and @bob"),
            ["alice", "bob"],
        )

    def test_group_tokens_lowercased(self):
        self.assertEqual(parse_mention_tokens("@ALL please"), ["all"])
        self.assertEqual(
            parse_mention_tokens("@Heads @HEALERS"),
            ["heads", "healers"],
        )

    def test_email_like_not_parsed(self):
        # foo@example.com must not be interpreted as a mention of
        # ``example`` — the ``(?<![\w@])`` lookbehind blocks the match
        # because ``o`` (a word char) precedes ``@``.
        self.assertEqual(
            parse_mention_tokens("reach me at foo@example.com"),
            [],
        )

    def test_url_like_not_parsed(self):
        self.assertEqual(
            parse_mention_tokens("Hello https://user@host.com/x"),
            [],
        )

    def test_trailing_period_stripped(self):
        self.assertEqual(parse_mention_tokens("ping @alice."), ["alice"])

    def test_sentence_punctuation_surrounding(self):
        self.assertEqual(
            parse_mention_tokens("(@alice, @bob) see this!"),
            ["alice", "bob"],
        )

    def test_double_at_not_matched(self):
        self.assertEqual(parse_mention_tokens("@@doubled"), [])

    def test_empty_and_none(self):
        self.assertEqual(parse_mention_tokens(""), [])
        self.assertEqual(parse_mention_tokens(None), [])

    def test_agent_style_username(self):
        self.assertEqual(
            parse_mention_tokens("attn @agent-foo"),
            ["agent-foo"],
        )


# ---------------------------------------------------------------------------
# 2. Group resolution
# ---------------------------------------------------------------------------


class ResolveMentionTargetsTest(TestCase):
    """Group-token expansion + fallback lookup."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="mention-resolve-ws")
        # Human members
        self.alice = User.objects.create_user("alice", password="x")
        self.bob = User.objects.create_user("bob", password="x")
        # Agent-shaped members
        self.head_mba = User.objects.create_user("agent-head-mba", password="x")
        self.head_spa = User.objects.create_user("agent-head-spartan", password="x")
        self.healer = User.objects.create_user("agent-healer-mba", password="x")
        self.worker = User.objects.create_user("agent-worker-bee", password="x")
        for u in [
            self.alice,
            self.bob,
            self.head_mba,
            self.head_spa,
            self.healer,
            self.worker,
        ]:
            WorkspaceMember.objects.create(workspace=self.ws, user=u, role="member")

    def test_bare_human_resolved(self):
        self.assertEqual(
            resolve_mention_targets(self.ws.id, ["alice"]),
            ["alice"],
        )

    def test_bare_agent_short_name_resolved_to_synthetic(self):
        # ``@head-mba`` should map to ``agent-head-mba`` (the synthetic
        # username agents authenticate under).
        self.assertEqual(
            resolve_mention_targets(self.ws.id, ["head-mba"]),
            ["agent-head-mba"],
        )

    def test_heads_group_expansion(self):
        got = resolve_mention_targets(self.ws.id, ["heads"])
        self.assertEqual(set(got), {"agent-head-mba", "agent-head-spartan"})

    def test_healers_group_expansion(self):
        self.assertEqual(
            resolve_mention_targets(self.ws.id, ["healers"]),
            ["agent-healer-mba"],
        )

    def test_workers_group_expansion(self):
        self.assertEqual(
            resolve_mention_targets(self.ws.id, ["workers"]),
            ["agent-worker-bee"],
        )

    def test_all_group_expansion_excludes_sender(self):
        got = resolve_mention_targets(
            self.ws.id, ["all"], exclude_usernames=["alice"]
        )
        # alice is excluded; every other member appears once.
        self.assertNotIn("alice", got)
        self.assertIn("bob", got)
        self.assertIn("agent-head-mba", got)

    def test_dedupe_across_group_and_single(self):
        # @heads + @head-mba should not double-count head-mba.
        got = resolve_mention_targets(self.ws.id, ["heads", "head-mba"])
        self.assertEqual(got.count("agent-head-mba"), 1)

    def test_unknown_token_returns_nothing(self):
        self.assertEqual(
            resolve_mention_targets(self.ws.id, ["does-not-exist"]),
            [],
        )


# ---------------------------------------------------------------------------
# 3. End-to-end fan-out
# ---------------------------------------------------------------------------


_INMEM_CHANNELS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}


@override_settings(CHANNEL_LAYERS=_INMEM_CHANNELS)
class ExpandMentionsAndNotifyTest(TestCase):
    """Fan-out: DM lazy-create, metadata marker, dedupe, rate-limit."""

    def setUp(self):
        _reset_rate_limit_for_tests()
        self.ws = Workspace.objects.create(name="mention-e2e-ws")
        self.alice = User.objects.create_user("alice", password="x")
        self.bob = User.objects.create_user("bob", password="x")
        self.carol = User.objects.create_user("carol", password="x")
        self.head_mba = User.objects.create_user("agent-head-mba", password="x")
        for u in [self.alice, self.bob, self.carol, self.head_mba]:
            WorkspaceMember.objects.create(workspace=self.ws, user=u, role="member")
        self.source = Channel.objects.create(
            workspace=self.ws, name="#proj-neurovista", kind=Channel.KIND_GROUP
        )

    def _notify(self, text, sender="alice", channel=None):
        return expand_mentions_and_notify(
            workspace_id=self.ws.id,
            source_channel=channel or self.source.name,
            source_msg_id=None,
            sender_username=sender,
            text=text,
        )

    def test_bare_mention_creates_dm_notification(self):
        res = self._notify("hey @bob look at this")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["recipient"], "bob")
        # The DM now exists with a mention-push message.
        dm = Channel.objects.get(workspace=self.ws, name=res[0]["dm"])
        self.assertEqual(dm.kind, Channel.KIND_DM)
        msgs = list(Message.objects.filter(channel=dm))
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].metadata["kind"], "mention-push")
        self.assertEqual(msgs[0].metadata["source_channel"], "#proj-neurovista")

    def test_two_distinct_mentions_generate_two_notifications(self):
        res = self._notify("ping @bob and @carol")
        self.assertEqual({r["recipient"] for r in res}, {"bob", "carol"})

    def test_duplicate_mention_dedupes_to_one(self):
        res = self._notify("@bob @bob @bob")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["recipient"], "bob")

    def test_group_mention_fan_out(self):
        # @heads should resolve to agent-head-mba and create a DM notif.
        res = self._notify("heads up @heads", sender="alice")
        recipients = {r["recipient"] for r in res}
        self.assertIn("agent-head-mba", recipients)

    def test_subscriber_recipient_skipped(self):
        # If bob is already subscribed to the source channel, no DM
        # mention-push should be generated.
        ChannelMembership.objects.create(user=self.bob, channel=self.source)
        res = self._notify("hey @bob")
        self.assertEqual(res, [])

    def test_email_like_does_not_notify(self):
        res = self._notify("contact foo@example.com for help")
        self.assertEqual(res, [])

    def test_url_like_does_not_notify(self):
        res = self._notify("see https://user@host.com")
        self.assertEqual(res, [])

    def test_dm_source_channel_skipped(self):
        # A mention inside a DM thread does not trigger cross-push.
        res = self._notify(
            "hey @carol check", channel="dm:human:alice|human:bob"
        )
        self.assertEqual(res, [])

    def test_sender_self_excluded_on_all(self):
        res = self._notify("@all standup time", sender="alice")
        recipients = {r["recipient"] for r in res}
        self.assertNotIn("alice", recipients)
        # Other members should be in there.
        self.assertIn("bob", recipients)

    def test_all_rate_limit_kicks_in_on_fourth_call(self):
        # Default cap is 3 @all per minute per sender.
        for _ in range(3):
            res = self._notify("@all ping", sender="alice")
            self.assertTrue(res, "first three @all should fan out")
        # Fourth invocation must be rate-limited → empty result.
        res4 = self._notify("@all ping", sender="alice")
        self.assertEqual(res4, [])

    def test_all_rate_limit_env_override(self):
        # Override the cap to 1 via env var.
        _reset_rate_limit_for_tests()
        with mock.patch.dict(
            os.environ, {"SCITEX_OROCHI_MENTION_ALL_RATE_LIMIT_PER_MIN": "1"}
        ):
            self.assertTrue(self._notify("@all one", sender="alice"))
            self.assertEqual(self._notify("@all two", sender="alice"), [])

    def test_rate_limit_does_not_affect_non_all_mentions(self):
        # Even after @all is capped, a plain @bob mention still goes.
        _reset_rate_limit_for_tests()
        with mock.patch.dict(
            os.environ, {"SCITEX_OROCHI_MENTION_ALL_RATE_LIMIT_PER_MIN": "0"}
        ):
            res = self._notify("@all @bob hi", sender="alice")
            recipients = {r["recipient"] for r in res}
            # @all was suppressed (cap=0); @bob still fans out.
            self.assertEqual(recipients, {"bob"})

    def test_empty_text_returns_empty(self):
        self.assertEqual(self._notify(""), [])

    def test_no_mentions_returns_empty(self):
        self.assertEqual(self._notify("no tokens here"), [])
