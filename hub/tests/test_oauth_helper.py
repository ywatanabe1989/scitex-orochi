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


class ReadOauthMetadataHelperTest(TestCase):
    """todo#265: unit tests for the read_oauth_metadata() helper.

    The helper lives in the canonical agent_meta.py shipped from
    ``.dotfiles/src/.scitex/orochi/scripts/agent_meta.py`` (see PR
    body for dotfiles sync notes). This test imports it directly
    from that path so the scitex-orochi hub test suite guards the
    token-leak regression even though the helper lives upstream.
    """

    DOTFILES_AGENT_META = (
        "/Users/ywatanabe/.dotfiles/src/.scitex/orochi/scripts/agent_meta.py"
    )

    def _import_helper(self):
        import importlib.util
        import os

        if not os.path.isfile(self.DOTFILES_AGENT_META):
            self.skipTest("dotfiles agent_meta.py not present on this host")
        spec = importlib.util.spec_from_file_location(
            "agent_meta_under_test", self.DOTFILES_AGENT_META
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_missing_file_returns_empty(self):
        mod = self._import_helper()
        from pathlib import Path

        result = mod.read_oauth_metadata(Path("/nonexistent/.claude.json"))
        self.assertEqual(result, {})

    def test_all_nine_keys_extracted(self):
        import tempfile
        from pathlib import Path

        mod = self._import_helper()
        doc = {
            "hasAvailableSubscription": True,
            "cachedExtraUsageDisabledReason": "out_of_credits",
            "oauthAccount": {
                "accountUuid": "uuid-abc",
                "emailAddress": "alice@example.org",
                "organizationUuid": "org-uuid",
                "organizationName": "Acme",
                "hasExtraUsageEnabled": False,
                "billingType": "subscription",
                "accountCreatedAt": "2024-01-01",
                "subscriptionCreatedAt": "2025-01-01T00:00:00Z",
                "displayName": "Alice",
                "organizationRole": "admin",
                "workspaceRole": "member",
            },
            # Hostile fields — must not appear in output.
            "accessToken": "sk-ant-oat01-should-not-leak",
            "refreshToken": "sk-ant-ort01-should-not-leak",
            "claudeAiOauth": {"accessToken": "sk-ant-oat01-nested-leak"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(doc, f)
            path = Path(f.name)
        try:
            result = mod.read_oauth_metadata(path)
            expected_keys = {
                "oauth_email",
                "oauth_org_name",
                "oauth_account_uuid",
                "oauth_display_name",
                "billing_type",
                "has_available_subscription",
                "usage_disabled_reason",
                "has_extra_usage_enabled",
                "subscription_created_at",
            }
            self.assertEqual(set(result.keys()), expected_keys)
            self.assertEqual(result["oauth_email"], "alice@example.org")
            self.assertEqual(result["oauth_org_name"], "Acme")
            self.assertEqual(result["oauth_account_uuid"], "uuid-abc")
            self.assertEqual(result["oauth_display_name"], "Alice")
            self.assertEqual(result["billing_type"], "subscription")
            self.assertEqual(result["has_available_subscription"], True)
            self.assertEqual(result["usage_disabled_reason"], "out_of_credits")
            self.assertEqual(result["has_extra_usage_enabled"], False)
            self.assertEqual(result["subscription_created_at"], "2025-01-01T00:00:00Z")
        finally:
            path.unlink()

    def test_token_leak_regression(self):
        """CRITICAL: hostile top-level fields must never appear in output.

        This is the primary security invariant for todo#265. If a
        future edit blacklist-converts the extractor, or adds a new
        whitelist key, this test catches leakage of any substring
        that looks like a Claude Code token/credential.
        """
        import tempfile
        from pathlib import Path

        mod = self._import_helper()
        hostile = {
            "oauthAccount": {
                "emailAddress": "eve@example.org",
                # Hostile nested field — still must not leak.
                "accessToken": "sk-ant-oat01-nested-should-not-leak",
            },
            "accessToken": "sk-ant-oat01-top-should-not-leak",
            "refreshToken": "sk-ant-ort01-top-should-not-leak",
            "apiKey": "sk-ant-api03-top-should-not-leak",
            "bearer": "Bearer should-not-leak",
            "credentials": {"apiKey": "sk-ant-api03-inner-should-not-leak"},
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-claudeai-should-not-leak",
                "refreshToken": "sk-ant-ort01-claudeai-should-not-leak",
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(hostile, f)
            path = Path(f.name)
        try:
            result = mod.read_oauth_metadata(path)
            # Whitelist: no key name should contain token/secret/key.
            for k in result.keys():
                kl = k.lower()
                self.assertNotIn("token", kl)
                self.assertNotIn("secret", kl)
                # "key" substring is too broad (would trip "oauth_email"
                # if we were sloppy); use endswith instead.
                self.assertFalse(kl.endswith("key"), f"forbidden key-like field: {k}")
            # And no value should contain the leaked substrings.
            flat = json.dumps(result).lower()
            forbidden_substrings = (
                "sk-ant-oat01",
                "sk-ant-ort01",
                "sk-ant-api03",
                "should-not-leak",
                "bearer",
            )
            for s in forbidden_substrings:
                self.assertNotIn(s, flat, f"token material {s!r} leaked into output")
        finally:
            path.unlink()
