"""Integration test: start server, connect two agents, exchange messages."""

from __future__ import annotations

import asyncio

import pytest
import websockets

from scitex_orochi._models import Message
from scitex_orochi._server import OrochiServer

TEST_HOST = "127.0.0.1"
TEST_PORT = 19559
TEST_TOKEN = "test-token-for-integration"


@pytest.fixture()
def server_port():
    return TEST_PORT


@pytest.fixture(autouse=True)
def _set_test_token(monkeypatch):
    """All tests run with a known token."""
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", TEST_TOKEN)
    import importlib

    import scitex_orochi._config

    importlib.reload(scitex_orochi._config)


@pytest.fixture()
async def orochi_server(tmp_path):
    """Start an Orochi server on a test port, yield, then shut down."""
    db_path = tmp_path / "test.db"
    srv = OrochiServer(host=TEST_HOST, port=TEST_PORT)
    srv.store.db_path = str(db_path)
    await srv.store.open()
    ws_server = await websockets.serve(srv._handle_connection, TEST_HOST, TEST_PORT)
    yield srv
    ws_server.close()
    await ws_server.wait_closed()
    await srv.store.close()


async def _register(ws, name: str, channels: list[str]) -> Message:
    reg = Message(type="register", sender=name, payload={"channels": channels})
    await ws.send(reg.to_json())
    raw = await ws.recv()
    return Message.from_json(raw)


@pytest.mark.asyncio
async def test_register_and_message(orochi_server):
    """Two agents register, one sends a message, the other receives it."""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token={TEST_TOKEN}"

    async with websockets.connect(uri) as ws_a, websockets.connect(uri) as ws_b:
        await _register(ws_a, "agent-a", ["#general"])
        await _register(ws_b, "agent-b", ["#general"])

        # Agent A sends a message
        msg = Message(
            type="message",
            sender="agent-a",
            payload={"channel": "#general", "content": "hello from A"},
        )
        await ws_a.send(msg.to_json())

        # Agent A gets an ack
        ack_raw = await asyncio.wait_for(ws_a.recv(), timeout=2.0)
        ack = Message.from_json(ack_raw)
        assert ack.type == "ack"

        # Agent B receives the message
        recv_raw = await asyncio.wait_for(ws_b.recv(), timeout=2.0)
        recv = Message.from_json(recv_raw)
        assert recv.type == "message"
        assert recv.content == "hello from A"
        assert recv.sender == "agent-a"


@pytest.mark.asyncio
async def test_mention_routing(orochi_server):
    """An @mention delivers to an agent not subscribed to the channel."""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token={TEST_TOKEN}"

    async with websockets.connect(uri) as ws_a, websockets.connect(uri) as ws_b:
        # Agent A subscribes to #project-x only
        await _register(ws_a, "agent-a", ["#project-x"])
        # Agent B subscribes to #general only
        await _register(ws_b, "agent-b", ["#general"])

        # Agent A sends to #project-x with @agent-b mention
        msg = Message(
            type="message",
            sender="agent-a",
            payload={
                "channel": "#project-x",
                "content": "@agent-b please review",
                "mentions": ["agent-b"],
            },
        )
        await ws_a.send(msg.to_json())

        # Agent B should receive it despite not being in #project-x
        recv_raw = await asyncio.wait_for(ws_b.recv(), timeout=2.0)
        recv = Message.from_json(recv_raw)
        assert recv.type == "message"
        assert "@agent-b" in recv.content


@pytest.mark.asyncio
async def test_presence(orochi_server):
    """Presence query returns online agents."""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token={TEST_TOKEN}"

    async with websockets.connect(uri) as ws_a:
        await _register(ws_a, "agent-a", ["#general"])

        pres = Message(type="presence", sender="agent-a")
        await ws_a.send(pres.to_json())

        # Skip the ack, get the presence response
        responses = []
        for _ in range(2):
            raw = await asyncio.wait_for(ws_a.recv(), timeout=2.0)
            responses.append(Message.from_json(raw))

        presence_msg = [r for r in responses if r.type == "presence"]
        assert len(presence_msg) == 1
        assert "agent-a" in presence_msg[0].payload["agents"]


@pytest.mark.asyncio
async def test_heartbeat(orochi_server):
    """Heartbeat updates last_heartbeat on the agent."""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token={TEST_TOKEN}"

    async with websockets.connect(uri) as ws_a:
        await _register(ws_a, "agent-a", ["#general"])
        old_hb = orochi_server.agents["agent-a"].last_heartbeat

        # Small delay to ensure timestamp differs
        await asyncio.sleep(0.05)

        hb = Message(type="heartbeat", sender="agent-a")
        await ws_a.send(hb.to_json())

        # Wait for ack
        ack_raw = await asyncio.wait_for(ws_a.recv(), timeout=2.0)
        ack = Message.from_json(ack_raw)
        assert ack.type == "ack"

        new_hb = orochi_server.agents["agent-a"].last_heartbeat
        assert new_hb >= old_hb


@pytest.mark.asyncio
async def test_status_update(orochi_server):
    """Status update changes agent status and orochi_current_task."""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token={TEST_TOKEN}"

    async with websockets.connect(uri) as ws_a:
        await _register(ws_a, "agent-a", ["#general"])

        su = Message(
            type="status_update",
            sender="agent-a",
            payload={"status": "busy", "orochi_current_task": "running tests"},
        )
        await ws_a.send(su.to_json())

        # Wait for ack
        ack_raw = await asyncio.wait_for(ws_a.recv(), timeout=2.0)
        ack = Message.from_json(ack_raw)
        assert ack.type == "ack"

        agent = orochi_server.agents["agent-a"]
        assert agent.status == "busy"
        assert agent.orochi_current_task == "running tests"


@pytest.mark.asyncio
async def test_auth_rejection(tmp_path, monkeypatch):
    """Connection with wrong token is rejected when SCITEX_OROCHI_TOKEN is set."""
    # Set a token on the server side
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "secret-test-token")
    # Re-import to pick up new env value
    import importlib

    import scitex_orochi._config

    importlib.reload(scitex_orochi._config)

    try:
        db_path = tmp_path / "test_auth.db"
        srv = OrochiServer(host=TEST_HOST, port=19560)
        srv.store.db_path = str(db_path)
        await srv.store.open()
        ws_server = await websockets.serve(srv._handle_connection, TEST_HOST, 19560)

        try:
            # Connect without token -- should get error then close
            uri_no_token = f"ws://{TEST_HOST}:19560"
            async with websockets.connect(uri_no_token) as ws_bad:
                raw = await asyncio.wait_for(ws_bad.recv(), timeout=2.0)
                msg = Message.from_json(raw)
                assert msg.type == "error"
                assert msg.payload["code"] == "AUTH_FAILED"

            # Connect with correct token -- should succeed
            uri_with_token = f"ws://{TEST_HOST}:19560/?token=secret-test-token"
            async with websockets.connect(uri_with_token) as ws_good:
                reg = Message(
                    type="register",
                    sender="authed-agent",
                    payload={"channels": ["#general"]},
                )
                await ws_good.send(reg.to_json())
                ack_raw = await asyncio.wait_for(ws_good.recv(), timeout=2.0)
                ack = Message.from_json(ack_raw)
                assert ack.type == "ack"
        finally:
            ws_server.close()
            await ws_server.wait_closed()
            await srv.store.close()
    finally:
        # Restore empty token
        monkeypatch.delenv("SCITEX_OROCHI_TOKEN", raising=False)
        importlib.reload(scitex_orochi._config)


@pytest.mark.asyncio
async def test_extended_agent_fields(orochi_server):
    """Register with orochi_machine and role fields, verify they are stored."""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token={TEST_TOKEN}"

    async with websockets.connect(uri) as ws_a:
        reg = Message(
            type="register",
            sender="agent-x",
            payload={
                "channels": ["#general"],
                "orochi_machine": "gpu-server-01",
                "role": "worker",
            },
        )
        await ws_a.send(reg.to_json())
        ack_raw = await asyncio.wait_for(ws_a.recv(), timeout=2.0)
        ack = Message.from_json(ack_raw)
        assert ack.type == "ack"

        agent = orochi_server.agents["agent-x"]
        assert agent.orochi_machine == "gpu-server-01"
        assert agent.role == "worker"
        assert agent.status == "online"
        assert agent.registered_at != ""


@pytest.mark.asyncio
async def test_get_agents_info(orochi_server):
    """get_agents_info returns correct REST-compatible dicts."""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token={TEST_TOKEN}"

    async with websockets.connect(uri) as ws_a:
        reg = Message(
            type="register",
            sender="info-agent",
            payload={
                "channels": ["#general"],
                "orochi_machine": "nas-01",
                "role": "builder",
            },
        )
        await ws_a.send(reg.to_json())
        await asyncio.wait_for(ws_a.recv(), timeout=2.0)

        info = orochi_server.get_agents_info()
        assert len(info) == 1
        assert info[0]["name"] == "info-agent"
        assert info[0]["orochi_machine"] == "nas-01"
        assert info[0]["role"] == "builder"
        assert "channels" in info[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
