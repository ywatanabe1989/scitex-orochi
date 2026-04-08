"""Tests for TelegramBridge -- Orochi <-> Telegram relay."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scitex_orochi._models import Message
from scitex_orochi._server import OrochiServer
from scitex_orochi._telegram_bridge import TelegramBridge

TEST_TOKEN = "123456:ABC-DEF"
TEST_CHAT_ID = "999888"
TEST_CHANNEL = "#telegram"


@pytest.fixture()
async def bridge_and_server(tmp_path):
    """Create a TelegramBridge with a real OrochiServer (in-memory DB)."""
    db_path = tmp_path / "test_bridge.db"
    srv = OrochiServer(host="127.0.0.1", port=19570)
    srv.store.db_path = str(db_path)
    await srv.store.open()

    bridge = TelegramBridge(
        bot_token=TEST_TOKEN,
        chat_id=TEST_CHAT_ID,
        server=srv,
        channel=TEST_CHANNEL,
    )
    # Do NOT call bridge.start() -- we test methods individually without
    # actually polling Telegram.
    yield bridge, srv
    await srv.store.close()


@pytest.mark.asyncio
async def test_relay_to_telegram_only_on_channel(bridge_and_server):
    """relay_to_telegram ignores messages NOT on #telegram."""
    bridge, srv = bridge_and_server
    bridge._session = MagicMock()

    msg = Message(
        type="message",
        sender="agent-a",
        payload={"channel": "#general", "content": "hello"},
    )
    # Should return immediately without calling _api
    with patch.object(bridge, "_api", new_callable=AsyncMock) as mock_api:
        await bridge.relay_to_telegram(msg)
        mock_api.assert_not_called()


@pytest.mark.asyncio
async def test_relay_to_telegram_skips_echo(bridge_and_server):
    """Messages originating from Telegram are not echoed back."""
    bridge, srv = bridge_and_server

    msg = Message(
        type="message",
        sender="Yusuke(@ywatanabe)",
        payload={
            "channel": TEST_CHANNEL,
            "content": "hi from telegram",
            "metadata": {"source": "telegram"},
        },
    )
    with patch.object(bridge, "_api", new_callable=AsyncMock) as mock_api:
        await bridge.relay_to_telegram(msg)
        mock_api.assert_not_called()


@pytest.mark.asyncio
async def test_relay_to_telegram_forwards_orochi_message(bridge_and_server):
    """A message on #telegram from an agent IS forwarded to Telegram."""
    bridge, srv = bridge_and_server

    msg = Message(
        type="message",
        sender="master",
        payload={
            "channel": TEST_CHANNEL,
            "content": "Task completed successfully.",
        },
    )
    with patch.object(
        bridge, "_api", new_callable=AsyncMock, return_value={"message_id": 42}
    ) as mock_api:
        await bridge.relay_to_telegram(msg)
        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert call_args[0][0] == "sendMessage"
        params = call_args[0][1]
        assert params["chat_id"] == TEST_CHAT_ID
        assert "[master]" in params["text"]
        assert "Task completed" in params["text"]


@pytest.mark.asyncio
async def test_relay_to_telegram_with_reply_to(bridge_and_server):
    """If metadata has reply_to_telegram_message_id, it is used."""
    bridge, srv = bridge_and_server

    msg = Message(
        type="message",
        sender="master",
        payload={
            "channel": TEST_CHANNEL,
            "content": "replying to your question",
            "metadata": {"reply_to_telegram_message_id": 123},
        },
    )
    with patch.object(
        bridge, "_api", new_callable=AsyncMock, return_value={"message_id": 43}
    ) as mock_api:
        await bridge.relay_to_telegram(msg)
        params = mock_api.call_args[0][1]
        assert params["reply_to_message_id"] == 123


@pytest.mark.asyncio
async def test_process_update_creates_orochi_message(bridge_and_server):
    """A Telegram update is converted into an Orochi Message on #telegram."""
    bridge, srv = bridge_and_server
    received_messages: list[Message] = []

    # Patch _handle_message to capture what gets posted
    original = srv._handle_message

    async def capture(msg):
        received_messages.append(msg)
        # Still call original to persist, etc.
        await original(msg)

    srv._handle_message = capture

    update = {
        "update_id": 100,
        "message": {
            "message_id": 42,
            "from": {"first_name": "Yusuke", "username": "ywatanabe"},
            "chat": {"id": int(TEST_CHAT_ID)},
            "text": "Please check the build status",
        },
    }
    await bridge._process_update(update)

    assert len(received_messages) == 1
    msg = received_messages[0]
    assert msg.channel == TEST_CHANNEL
    assert msg.content == "Please check the build status"
    assert msg.sender == "Yusuke(@ywatanabe)"
    metadata = msg.payload.get("metadata", {})
    assert metadata["source"] == "telegram"
    assert metadata["telegram_chat_id"] == TEST_CHAT_ID
    assert metadata["telegram_message_id"] == 42
    assert metadata["telegram_username"] == "ywatanabe"


@pytest.mark.asyncio
async def test_process_update_ignores_wrong_chat(bridge_and_server):
    """Messages from a different chat_id are ignored."""
    bridge, srv = bridge_and_server
    received: list[Message] = []

    async def capture(msg):
        received.append(msg)

    srv._handle_message = capture

    update = {
        "update_id": 101,
        "message": {
            "message_id": 43,
            "from": {"first_name": "Stranger"},
            "chat": {"id": 111222},  # wrong chat
            "text": "should be ignored",
        },
    }
    await bridge._process_update(update)
    assert len(received) == 0


@pytest.mark.asyncio
async def test_process_update_with_photo(bridge_and_server):
    """Photo attachments are included in the Orochi message."""
    bridge, srv = bridge_and_server
    received: list[Message] = []

    async def capture(msg):
        received.append(msg)

    srv._handle_message = capture

    update = {
        "update_id": 102,
        "message": {
            "message_id": 44,
            "from": {"first_name": "Yusuke"},
            "chat": {"id": int(TEST_CHAT_ID)},
            "caption": "Look at this",
            "photo": [
                {"file_id": "small_id", "file_size": 100},
                {"file_id": "large_id", "file_size": 5000},
            ],
        },
    }
    await bridge._process_update(update)
    assert len(received) == 1
    attachments = received[0].payload.get("attachments", [])
    assert len(attachments) == 1
    assert attachments[0]["file_id"] == "large_id"
    assert attachments[0]["type"] == "photo"


@pytest.mark.asyncio
async def test_process_update_with_voice(bridge_and_server):
    """Voice messages are included as attachments."""
    bridge, srv = bridge_and_server
    received: list[Message] = []

    async def capture(msg):
        received.append(msg)

    srv._handle_message = capture

    update = {
        "update_id": 103,
        "message": {
            "message_id": 45,
            "from": {"first_name": "Yusuke"},
            "chat": {"id": int(TEST_CHAT_ID)},
            "voice": {"file_id": "voice_123", "duration": 5},
        },
    }
    await bridge._process_update(update)
    assert len(received) == 1
    attachments = received[0].payload.get("attachments", [])
    assert len(attachments) == 1
    assert attachments[0]["type"] == "voice"
    assert attachments[0]["file_id"] == "voice_123"


@pytest.mark.asyncio
async def test_setup_telegram_bridge_disabled(tmp_path, monkeypatch):
    """setup_telegram_bridge returns None when disabled."""
    monkeypatch.setenv("SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED", "false")
    import importlib

    import scitex_orochi._config

    importlib.reload(scitex_orochi._config)

    try:
        from scitex_orochi._telegram_bridge import setup_telegram_bridge

        srv = OrochiServer(host="127.0.0.1", port=19571)
        srv.store.db_path = str(tmp_path / "disabled.db")
        await srv.store.open()
        result = await setup_telegram_bridge(srv)
        assert result is None
        await srv.store.close()
    finally:
        monkeypatch.delenv("SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED", raising=False)
        importlib.reload(scitex_orochi._config)


@pytest.mark.asyncio
async def test_setup_telegram_bridge_missing_token(tmp_path, monkeypatch):
    """setup_telegram_bridge returns None and logs ERROR when token missing."""
    monkeypatch.setenv("SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED", "true")
    monkeypatch.delenv("SCITEX_OROCHI_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SCITEX_OROCHI_TELEGRAM_BOT_TOKEN", raising=False)
    import importlib

    import scitex_orochi._config

    importlib.reload(scitex_orochi._config)

    try:
        from scitex_orochi._telegram_bridge import setup_telegram_bridge

        srv = OrochiServer(host="127.0.0.1", port=19572)
        srv.store.db_path = str(tmp_path / "no_token.db")
        await srv.store.open()
        result = await setup_telegram_bridge(srv)
        assert result is None
        await srv.store.close()
    finally:
        monkeypatch.delenv("SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED", raising=False)
        importlib.reload(scitex_orochi._config)
