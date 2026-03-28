"""Tests for the Orochi HTTP/Dashboard web layer."""

from __future__ import annotations

import asyncio

import pytest
import websockets
from aiohttp.test_utils import TestClient, TestServer

from orochi.models import Message
from orochi.server import OrochiServer
from orochi.web import create_web_app

TEST_HOST = "127.0.0.1"
TEST_WS_PORT = 19561


@pytest.fixture()
async def orochi_web(tmp_path):
    """Start Orochi server + aiohttp test client."""
    db_path = tmp_path / "test_web.db"
    srv = OrochiServer(host=TEST_HOST, port=TEST_WS_PORT)
    srv.store.db_path = str(db_path)
    await srv.store.open()

    # Start WebSocket server for agents
    ws_server = await websockets.serve(srv._handle_connection, TEST_HOST, TEST_WS_PORT)

    # Create aiohttp test client
    app = create_web_app(srv)
    client = TestClient(TestServer(app))
    await client.start_server()

    yield srv, client

    await client.close()
    ws_server.close()
    await ws_server.wait_closed()
    await srv.store.close()


async def _register_agent(host, port, name, channels, **kwargs):
    """Helper to register an agent via WebSocket."""
    uri = f"ws://{host}:{port}"
    ws = await websockets.connect(uri)
    payload = {"channels": channels}
    payload.update(kwargs)
    reg = Message(type="register", sender=name, payload=payload)
    await ws.send(reg.to_json())
    await asyncio.wait_for(ws.recv(), timeout=2.0)  # ack
    return ws


@pytest.mark.asyncio
async def test_api_agents(orochi_web):
    """GET /api/agents returns connected agents."""
    srv, client = orochi_web

    # No agents yet
    resp = await client.get("/api/agents")
    assert resp.status == 200
    data = await resp.json()
    assert data == []

    # Register an agent
    ws = await _register_agent(
        TEST_HOST,
        TEST_WS_PORT,
        "test-agent",
        ["#general"],
        machine="laptop",
        role="developer",
    )
    try:
        resp = await client.get("/api/agents")
        assert resp.status == 200
        data = await resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "test-agent"
        assert data[0]["machine"] == "laptop"
        assert data[0]["role"] == "developer"
    finally:
        await ws.close()


@pytest.mark.asyncio
async def test_api_channels(orochi_web):
    """GET /api/channels returns channel membership."""
    srv, client = orochi_web

    ws = await _register_agent(
        TEST_HOST, TEST_WS_PORT, "ch-agent", ["#general", "#dev"]
    )
    try:
        resp = await client.get("/api/channels")
        assert resp.status == 200
        data = await resp.json()
        assert "ch-agent" in data.get("#general", [])
        assert "ch-agent" in data.get("#dev", [])
    finally:
        await ws.close()


@pytest.mark.asyncio
async def test_api_stats(orochi_web):
    """GET /api/stats returns server statistics."""
    srv, client = orochi_web

    resp = await client.get("/api/stats")
    assert resp.status == 200
    data = await resp.json()
    assert "agents_online" in data
    assert "channels_active" in data
    assert "observers_connected" in data


@pytest.mark.asyncio
async def test_api_history(orochi_web):
    """GET /api/history/{channel} returns message history."""
    srv, client = orochi_web

    # Save a message to store directly
    await srv.store.save(
        msg_id="test-msg-1",
        ts="2026-01-01T00:00:00Z",
        channel="#general",
        sender="test-sender",
        content="hello world",
    )

    resp = await client.get("/api/history/general")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["content"] == "hello world"
    assert data[0]["sender"] == "test-sender"


@pytest.mark.asyncio
async def test_dashboard_index(orochi_web):
    """GET / serves the dashboard page."""
    srv, client = orochi_web

    resp = await client.get("/")
    assert resp.status == 200


@pytest.mark.asyncio
async def test_dashboard_ws_observer(orochi_web):
    """Dashboard WebSocket receives messages broadcast from agents."""
    srv, client = orochi_web

    # Connect dashboard observer via aiohttp test client
    ws_dashboard = await client.ws_connect("/ws")

    # Register an agent and send a message
    ws_agent = await _register_agent(TEST_HOST, TEST_WS_PORT, "obs-agent", ["#general"])
    try:
        msg = Message(
            type="message",
            sender="obs-agent",
            payload={"channel": "#general", "content": "observed message"},
        )
        await ws_agent.send(msg.to_json())

        # Dashboard receives all broadcasts; drain until we get the message type
        # (presence_change from registration arrives first)
        dashboard_msg = None
        for _ in range(5):
            raw = await asyncio.wait_for(ws_dashboard.receive_json(), timeout=2.0)
            if raw.get("type") == "message":
                dashboard_msg = raw
                break
        assert dashboard_msg is not None
        assert dashboard_msg["payload"]["content"] == "observed message"
    finally:
        await ws_dashboard.close()
        await ws_agent.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
