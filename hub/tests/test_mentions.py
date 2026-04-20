"""Tests for the Orochi hub Django app."""

import json  # noqa: F401
from unittest.mock import MagicMock, patch  # noqa: F401

from django.contrib.auth.models import User  # noqa: F401
from django.core.exceptions import ValidationError  # noqa: F401
from django.db import IntegrityError, transaction  # noqa: F401
from django.test import Client, TestCase  # noqa: F401

from hub import push as hub_push  # noqa: F401
from hub.models import (  # noqa: F401
    Channel,
    ChannelMembership,
    DMParticipant,
    Message,
    PushSubscription,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
    normalize_channel_name,
)


class GroupMentionExpansionTest(TestCase):
    """Regression guard for @heads/@healers/@mambas/@all/@agents expansion.

    The frontend chip renderer in hub/static/hub/chat.js hard-codes the
    same five group tokens as the hub-side GROUP_PATTERNS dict in
    hub/consumers.py (introduced in 526c490). If either side drifts the
    user will see a chip that the backend refuses to expand (or vice
    versa). This test asserts both sides still agree — todo#421.
    """

    #: Must match MENTION_GROUP_TOKENS in hub/static/hub/chat.js and the
    #: GROUP_PATTERNS dict in hub/consumers.py._maybe_mention_reply.
    EXPECTED_TOKENS = {"heads", "healers", "mambas", "all", "agents"}

    def test_consumers_group_patterns_has_expected_tokens(self):
        """The consumers package still declares all five group tokens.

        After the consumers.py → consumers/ package split, GROUP_PATTERNS
        lives in the dashboard ``message`` handler at
        ``hub/consumers/_dashboard_message.py``.
        """
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1] / "consumers" / "_dashboard_message.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "GROUP_PATTERNS = {",
            src,
            "consumers package lost the GROUP_PATTERNS dict (526c490 regression)",
        )
        for token in self.EXPECTED_TOKENS:
            self.assertIn(
                f'"{token}"',
                src,
                f"GROUP_PATTERNS missing @{token} token",
            )

    def test_frontend_chat_js_has_matching_group_tokens(self):
        """chat.js MENTION_GROUP_TOKENS agrees with backend GROUP_PATTERNS."""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "hub"
            / "chat"
            / "chat-markdown.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "MENTION_GROUP_TOKENS",
            src,
            "chat.js missing MENTION_GROUP_TOKENS (todo#421)",
        )
        for token in self.EXPECTED_TOKENS:
            self.assertIn(
                f"{token}:",
                src,
                f"chat.js MENTION_GROUP_TOKENS missing @{token}",
            )

    def test_group_expansion_algorithm(self):
        """Pure-Python replication of the consumer's expansion step.

        Guards the algorithm shape (startswith rules + dedupe-preserving
        order) without requiring an async consumer harness.
        """
        GROUP_PATTERNS = {
            "heads": lambda n: n.startswith("head-"),
            "healers": lambda n: n.startswith("mamba-healer"),
            "mambas": lambda n: n.startswith("mamba-"),
            "all": lambda n: True,
            "agents": lambda n: True,
        }
        all_names = [
            "head-mba",
            "head-spartan",
            "mamba-healer-mba",
            "mamba-todo-manager",
            "ywata-note-win",
        ]

        def expand(mentioned):
            out: list[str] = []
            for tok in mentioned:
                if tok in GROUP_PATTERNS:
                    out.extend(n for n in all_names if GROUP_PATTERNS[tok](n))
                else:
                    out.append(tok)
            return list(dict.fromkeys(out))

        self.assertEqual(
            expand(["heads"]),
            ["head-mba", "head-spartan"],
        )
        self.assertEqual(
            expand(["healers"]),
            ["mamba-healer-mba"],
        )
        self.assertEqual(
            expand(["mambas"]),
            ["mamba-healer-mba", "mamba-todo-manager"],
        )
        self.assertEqual(
            expand(["all"]),
            all_names,
        )
        # Dedupe: @heads + head-mba should not double-fire head-mba.
        self.assertEqual(
            expand(["heads", "head-mba"]),
            ["head-mba", "head-spartan"],
        )
        # Unknown tokens pass through unchanged.
        self.assertEqual(
            expand(["not-a-group", "heads"]),
            ["not-a-group", "head-mba", "head-spartan"],
        )
