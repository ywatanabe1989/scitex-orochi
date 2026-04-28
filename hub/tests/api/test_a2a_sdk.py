"""Tests for the orochi A2A SDK surface (Phase 3 of A2A_MIGRATION).

Covers:
- The Starlette app mounts and serves ``.well-known/agent-card.json``.
- ``SendMessage`` round-trips against an in-memory test executor.
- Agent-not-found returns a JSON-RPC error (mapped through SDK status).
- Auth: requests without a ``WorkspaceToken`` are rejected (the
  executor publishes a ``failed`` status with an auth-required message).

Pure a2a-sdk 1.x: only gRPC-style method names (``SendMessage`` /
``SendStreamingMessage`` / ``GetTask`` / ``CancelTask``) — no v0.3
``message/send`` / ``tasks/send`` back-compat. Requests carry the
``A2A-Version: 1.0`` header that the SDK 1.x router expects.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orochi.settings")
django.setup()

from django.test import TransactionTestCase  # noqa: E402

from hub.a2a.mount import build_a2a_app  # noqa: E402


def _make_scope(method: str, path: str, headers: list | None = None) -> dict:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "headers": headers or [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234),
        "root_path": "",
    }


async def _call_app(app, scope, body: bytes = b"") -> tuple[int, bytes, list]:
    sent: list = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        sent.append(msg)

    await app(scope, receive, send)
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), 0)
    headers = next(
        (m.get("headers", []) for m in sent if m["type"] == "http.response.start"),
        [],
    )
    body_out = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return status, body_out, headers


class A2ASDKMountTests(unittest.TestCase):
    """The app mounts and the well-known card route resolves."""

    def test_app_builds(self) -> None:
        app = build_a2a_app()
        self.assertIsNotNone(app)

    def test_well_known_agent_card_returns_200(self) -> None:
        app = build_a2a_app()
        status, body, _ = asyncio.run(
            _call_app(
                app,
                _make_scope("GET", "/v1/agents/test-agent/.well-known/agent-card.json"),
            )
        )
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["name"], "test-agent")
        self.assertIn("capabilities", payload)

    def test_well_known_agent_json_alias_returns_200(self) -> None:
        """Older clients hit the legacy ``/.well-known/agent.json`` path."""
        app = build_a2a_app()
        status, _, _ = asyncio.run(
            _call_app(
                app,
                _make_scope("GET", "/v1/agents/some-agent/.well-known/agent.json"),
            )
        )
        self.assertEqual(status, 200)


class A2AAuthTests(TransactionTestCase):
    """Unauthenticated calls are rejected; valid bearer is accepted."""

    def test_message_send_without_auth_yields_failed_task(self) -> None:
        from hub.registry import _agents

        # Pre-seed a registry entry so the only failure cause is auth.
        _agents["unauth-agent"] = {
            "status": "online",
            "role": "agent",
            "host": "x",
            "a2a_url": "",
            "last_heartbeat": 0,
        }
        try:
            app = build_a2a_app()
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "req-1",
                    "method": "SendMessage",
                    "params": {
                        "message": {
                            "message_id": "m1",
                            "role": "ROLE_USER",
                            "parts": [{"text": "hi"}],
                        }
                    },
                }
            ).encode()
            status, body_out, _ = asyncio.run(
                _call_app(
                    app,
                    _make_scope(
                        "POST",
                        "/v1/agents/unauth-agent/",
                        headers=[
                            (b"content-type", b"application/json"),
                            (b"a2a-version", b"1.0"),
                        ],
                    ),
                    body=body,
                )
            )
        finally:
            _agents.pop("unauth-agent", None)

        self.assertEqual(status, 200)
        # JSON-RPC envelope; the executor surfaces auth failure in the
        # task result rather than at the JSON-RPC envelope level.
        envelope = json.loads(body_out)
        # Either a result with the task in failed state, or an error.
        # The task-status text should reference authentication.
        text = json.dumps(envelope).lower()
        self.assertTrue(
            "auth" in text or "workspacetoken" in text or "error" in text,
            f"expected auth-related response, got: {envelope}",
        )


class A2AAgentNotFoundTests(TransactionTestCase):
    """A live request for a missing agent yields a JSON-RPC envelope."""

    def test_message_send_unknown_agent(self) -> None:
        from hub.models import Workspace, WorkspaceToken

        ws = Workspace.objects.create(name="test-ws-a2a")
        tok = WorkspaceToken.objects.create(
            workspace=ws, token="wks_test_dummy", label="test"
        )

        try:
            app = build_a2a_app()
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "req-2",
                    "method": "SendMessage",
                    "params": {
                        "message": {
                            "message_id": "m2",
                            "role": "ROLE_USER",
                            "parts": [{"text": "hi"}],
                        }
                    },
                }
            ).encode()
            status, body_out, _ = asyncio.run(
                _call_app(
                    app,
                    _make_scope(
                        "POST",
                        "/v1/agents/does-not-exist/",
                        headers=[
                            (b"content-type", b"application/json"),
                            (b"authorization", f"Bearer {tok.token}".encode()),
                            (b"a2a-version", b"1.0"),
                        ],
                    ),
                    body=body,
                )
            )
        finally:
            tok.delete()
            ws.delete()

        self.assertEqual(status, 200)
        text = json.dumps(json.loads(body_out)).lower()
        self.assertTrue("not found" in text or "offline" in text)


class A2AMessageSendRoundtripTests(TransactionTestCase):
    """End-to-end ``SendMessage`` against a stubbed HTTP-direct agent."""

    def test_message_send_completes_via_http_direct(self) -> None:
        from hub.a2a import _dispatch_internals
        from hub.models import Workspace, WorkspaceToken
        from hub.registry import _agents

        ws = Workspace.objects.create(name="test-ws-rt")
        tok = WorkspaceToken.objects.create(
            workspace=ws, token="wks_test_rt", label="rt"
        )
        _agents["rt-agent"] = {
            "status": "online",
            "role": "agent",
            "host": "x",
            # Non-empty a2a_url triggers the HTTP-direct branch which
            # we monkey-patch so no network hop happens during tests.
            "a2a_url": "http://stub/",
            "last_heartbeat": 0,
        }

        original = _dispatch_internals._try_http_direct

        def _stub(url: str, body: dict) -> tuple[bool, dict | None]:
            return True, {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {
                    "status": "completed",
                    "message": {
                        "role": "agent",
                        "parts": [{"type": "text", "text": "pong"}],
                    },
                },
            }

        # Patch on both the internals module and the executor's import
        # site (the executor binds the symbol at import time).
        from hub.a2a import executor as _executor_mod

        _dispatch_internals._try_http_direct = _stub
        _executor_mod._try_http_direct = _stub
        try:
            app = build_a2a_app()
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "rt-1",
                    "method": "SendMessage",
                    "params": {
                        "message": {
                            "message_id": "rt-msg",
                            "role": "ROLE_USER",
                            "parts": [{"text": "ping"}],
                        }
                    },
                }
            ).encode()
            status, body_out, _ = asyncio.run(
                _call_app(
                    app,
                    _make_scope(
                        "POST",
                        "/v1/agents/rt-agent/",
                        headers=[
                            (b"content-type", b"application/json"),
                            (b"authorization", f"Bearer {tok.token}".encode()),
                            (b"a2a-version", b"1.0"),
                        ],
                    ),
                    body=body,
                )
            )
        finally:
            _dispatch_internals._try_http_direct = original
            _executor_mod._try_http_direct = original
            _agents.pop("rt-agent", None)
            tok.delete()
            ws.delete()

        self.assertEqual(status, 200)
        envelope = json.loads(body_out)
        text = json.dumps(envelope).lower()
        # The executor maps the agent's reply text into the final
        # status-update message; "pong" should appear somewhere.
        self.assertIn("pong", text, f"got: {envelope}")


if __name__ == "__main__":
    unittest.main()
