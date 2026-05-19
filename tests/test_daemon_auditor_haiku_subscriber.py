"""Subscriber-loop tests for ``daemon-auditor-haiku`` Stage 1.

We don't spin up a real WebSocket — that would gold-plate the test.
Instead we drive ``_process_one_message`` directly with synthetic
``Message``-shaped objects and assert on what gets posted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from scitex_orochi._daemons._auditor_haiku._subscriber import (
    AuditCounters,
    AuditorConfig,
    _process_one_message,
)


@dataclass
class _FakeMessage:
    sender: str
    type: str = "message"
    payload: dict = field(default_factory=dict)


class _FakeClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, str]] = []

    async def send(self, channel: str, content: str, **_: Any) -> None:
        self.posts.append((channel, content))


@pytest.fixture
def cfg() -> AuditorConfig:
    return AuditorConfig(
        agent_name="daemon-auditor-haiku",
        publish_channel="#audit-shadow",
        emit_pass=True,
        fail_only=False,
    )


def _run(coro):
    return asyncio.run(coro)


def test_self_excludes_own_messages(cfg: AuditorConfig) -> None:
    client = _FakeClient()
    counters = AuditCounters()
    msg = _FakeMessage(
        sender="daemon-auditor-haiku",
        payload={"channel": "#audit-shadow", "content": "blocker", "metadata": {}},
    )
    _run(_process_one_message(msg, cfg=cfg, client=client, counters=counters))
    assert client.posts == []
    assert counters.self_excluded == 1
    assert counters.failed == 0


def test_fail_message_posts_to_shadow(cfg: AuditorConfig) -> None:
    client = _FakeClient()
    counters = AuditCounters()
    msg = _FakeMessage(
        sender="proj-foo",
        payload={
            "channel": "#general",
            "content": "Should I proceed?",
            "metadata": {"msg_id": 99},
        },
    )
    _run(_process_one_message(msg, cfg=cfg, client=client, counters=counters))
    assert len(client.posts) == 1
    channel, line = client.posts[0]
    assert channel == "#audit-shadow"
    assert "verdict=FAIL" in line
    assert "msg#99" in line
    assert counters.failed == 1


def test_pass_message_emits_pass_line_when_emit_pass(cfg: AuditorConfig) -> None:
    client = _FakeClient()
    counters = AuditCounters()
    msg = _FakeMessage(
        sender="proj-foo",
        payload={
            "channel": "#general",
            "content": "All tests pass; pushing.",
            "metadata": {"msg_id": 100},
        },
    )
    _run(_process_one_message(msg, cfg=cfg, client=client, counters=counters))
    assert len(client.posts) == 1
    assert "verdict=PASS" in client.posts[0][1]
    assert counters.passed == 1


def test_fail_only_suppresses_pass_lines() -> None:
    cfg = AuditorConfig(
        agent_name="daemon-auditor-haiku",
        publish_channel="#audit-shadow",
        fail_only=True,
    )
    client = _FakeClient()
    counters = AuditCounters()
    msg = _FakeMessage(
        sender="proj-foo",
        payload={"channel": "#general", "content": "All good.", "metadata": {}},
    )
    _run(_process_one_message(msg, cfg=cfg, client=client, counters=counters))
    assert client.posts == []
    assert counters.passed == 1
