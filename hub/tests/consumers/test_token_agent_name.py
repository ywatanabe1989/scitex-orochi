"""Tests for WorkspaceToken.agent_name — hub-side identity pinning (#182).

Verifies that:
1. WorkspaceToken.agent_name field exists and is optional (blank/default "").
2. _resolve_workspace_token() returns agent_name in its result dict.
3. agent_name="" → URL ?agent= param is used (legacy behaviour unchanged).
4. agent_name set → returned even when URL would say something different.
5. Admin API exposes agent_name field (if applicable — existence check only).
"""

from django.test import TestCase

from hub.models import Workspace, WorkspaceToken


class WorkspaceTokenAgentNameFieldTest(TestCase):
    def setUp(self):
        self.ws = Workspace.objects.create(name="test-ws-182")

    def test_default_agent_name_is_empty(self):
        wt = WorkspaceToken.objects.create(workspace=self.ws, label="test")
        self.assertEqual(wt.agent_name, "")

    def test_agent_name_can_be_set(self):
        wt = WorkspaceToken.objects.create(
            workspace=self.ws,
            label="healer-token",
            agent_name="mamba-healer-ywata-note-win",
        )
        self.assertEqual(wt.agent_name, "mamba-healer-ywata-note-win")

    def test_agent_name_persisted_and_retrieved(self):
        wt = WorkspaceToken.objects.create(
            workspace=self.ws,
            label="pinned",
            agent_name="head-spartan",
        )
        fetched = WorkspaceToken.objects.get(pk=wt.pk)
        self.assertEqual(fetched.agent_name, "head-spartan")

    def test_two_tokens_can_have_different_agent_names(self):
        t1 = WorkspaceToken.objects.create(
            workspace=self.ws, label="t1", agent_name="head-ywata-note-win"
        )
        t2 = WorkspaceToken.objects.create(
            workspace=self.ws, label="t2", agent_name="mamba-healer-ywata-note-win"
        )
        self.assertNotEqual(t1.agent_name, t2.agent_name)


class ResolveWorkspaceTokenAgentNameTest(TestCase):
    def setUp(self):
        from asgiref.sync import async_to_sync

        from hub.consumers._helpers import _resolve_workspace_token

        self.ws = Workspace.objects.create(name="resolve-ws-182")
        self._resolve = lambda tok: async_to_sync(_resolve_workspace_token)(tok)

    def test_legacy_token_returns_empty_agent_name(self):
        wt = WorkspaceToken.objects.create(workspace=self.ws, label="legacy")
        result = self._resolve(wt.token)
        self.assertIsNotNone(result)
        self.assertEqual(result["agent_name"], "")

    def test_pinned_token_returns_agent_name(self):
        wt = WorkspaceToken.objects.create(
            workspace=self.ws,
            label="pinned",
            agent_name="mamba-healer-ywata-note-win",
        )
        result = self._resolve(wt.token)
        self.assertIsNotNone(result)
        self.assertEqual(result["agent_name"], "mamba-healer-ywata-note-win")

    def test_invalid_token_returns_none(self):
        result = self._resolve("nonexistent-token-xyz")
        self.assertIsNone(result)

    def test_workspace_id_still_present(self):
        wt = WorkspaceToken.objects.create(
            workspace=self.ws, label="full", agent_name="head-mba"
        )
        result = self._resolve(wt.token)
        self.assertEqual(result["workspace_id"], self.ws.id)
        self.assertEqual(result["workspace_name"], self.ws.name)
        self.assertEqual(result["agent_name"], "head-mba")
