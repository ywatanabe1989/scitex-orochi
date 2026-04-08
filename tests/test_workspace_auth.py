"""Tests for workspace-based authentication and routing isolation."""

from __future__ import annotations

import asyncio
import importlib

import pytest
import websockets

from scitex_orochi._models import Message
from scitex_orochi._server import OrochiServer

TEST_HOST = "127.0.0.1"
TEST_PORT = 19562


@pytest.fixture(autouse=True)
def _set_admin_token(monkeypatch):
    """Set admin token for all tests."""
    monkeypatch.setenv("SCITEX_OROCHI_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "test-admin-token")
    import scitex_orochi._config

    importlib.reload(scitex_orochi._config)


@pytest.fixture()
async def workspace_server(tmp_path):
    """Start server with workspace support and two workspace tokens."""
    db_path = tmp_path / "test_ws.db"
    srv = OrochiServer(host=TEST_HOST, port=TEST_PORT)
    srv.store.db_path = str(db_path)
    await srv.store.open()

    from scitex_orochi._workspaces import WorkspaceStore

    srv.workspaces = WorkspaceStore(srv.store._db)
    await srv.workspaces.init_schema()

    # Create two workspaces with tokens
    ws_a = await srv.workspaces.create_workspace("lab-a", channels=["#general"])
    ws_b = await srv.workspaces.create_workspace("lab-b", channels=["#general"])
    token_a = await srv.workspaces.create_workspace_token(ws_a.id, "tok-a")
    token_b = await srv.workspaces.create_workspace_token(ws_b.id, "tok-b")

    ws_server = await websockets.serve(srv._handle_connection, TEST_HOST, TEST_PORT)

    yield srv, token_a["token"], token_b["token"]

    ws_server.close()
    await ws_server.wait_closed()
    await srv.store.close()


async def _register(ws, name, channels):
    reg = Message(type="register", sender=name, payload={"channels": channels})
    await ws.send(reg.to_json())
    raw = await ws.recv()
    return Message.from_json(raw)


@pytest.mark.asyncio
async def test_admin_token_connects(workspace_server):
    """Admin token should be accepted."""
    srv, _, _ = workspace_server
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token=test-admin-token"
    async with websockets.connect(uri) as ws:
        ack = await _register(ws, "admin-agent", ["#general"])
        assert ack.type == "ack"


@pytest.mark.asyncio
async def test_workspace_token_connects(workspace_server):
    """Workspace token should be accepted and assign workspace_id."""
    srv, tok_a, _ = workspace_server
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token={tok_a}"
    async with websockets.connect(uri) as ws:
        ack = await _register(ws, "agent-a", ["#general"])
        assert ack.type == "ack"
        agent = srv.agents["agent-a"]
        assert agent.workspace_id != ""


@pytest.mark.asyncio
async def test_invalid_token_rejected(workspace_server):
    """Invalid token should be rejected."""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token=bogus"
    async with websockets.connect(uri) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
        msg = Message.from_json(raw)
        assert msg.type == "error"
        assert msg.payload["code"] == "AUTH_FAILED"


@pytest.mark.asyncio
async def test_no_token_rejected(workspace_server):
    """No token should be rejected."""
    uri = f"ws://{TEST_HOST}:{TEST_PORT}"
    async with websockets.connect(uri) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
        msg = Message.from_json(raw)
        assert msg.type == "error"
        assert msg.payload["code"] == "AUTH_FAILED"


@pytest.mark.asyncio
async def test_workspace_isolation(workspace_server):
    """Agents in different workspaces should NOT see each other's messages."""
    srv, tok_a, tok_b = workspace_server
    uri_a = f"ws://{TEST_HOST}:{TEST_PORT}?token={tok_a}"
    uri_b = f"ws://{TEST_HOST}:{TEST_PORT}?token={tok_b}"

    async with websockets.connect(uri_a) as ws_a, websockets.connect(uri_b) as ws_b:
        await _register(ws_a, "agent-a", ["#general"])
        await _register(ws_b, "agent-b", ["#general"])

        # Agent A sends to #general
        msg = Message(
            type="message",
            sender="agent-a",
            payload={"channel": "#general", "content": "hello from lab-a"},
        )
        await ws_a.send(msg.to_json())
        # Consume ack for agent-a
        await asyncio.wait_for(ws_a.recv(), timeout=2.0)

        # Agent B should NOT receive it (different workspace)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws_b.recv(), timeout=0.5)


@pytest.mark.asyncio
async def test_same_workspace_delivery(workspace_server):
    """Agents in the same workspace SHOULD see each other's messages."""
    srv, tok_a, _ = workspace_server
    uri = f"ws://{TEST_HOST}:{TEST_PORT}?token={tok_a}"

    async with websockets.connect(uri) as ws_1, websockets.connect(uri) as ws_2:
        await _register(ws_1, "agent-1", ["#general"])
        await _register(ws_2, "agent-2", ["#general"])

        msg = Message(
            type="message",
            sender="agent-1",
            payload={"channel": "#general", "content": "hello teammate"},
        )
        await ws_1.send(msg.to_json())
        # Consume ack for agent-1
        await asyncio.wait_for(ws_1.recv(), timeout=2.0)

        # Agent 2 should receive it (same workspace)
        raw = await asyncio.wait_for(ws_2.recv(), timeout=2.0)
        recv = Message.from_json(raw)
        assert recv.type == "message"
        assert recv.content == "hello teammate"
