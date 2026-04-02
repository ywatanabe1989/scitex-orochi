"""Telegram Bridge -- relay messages between Orochi and Telegram Bot API.

Architecture:
  User (iPhone Telegram)
    -> Telegram Bot API
    -> orochi-server (polls via TelegramBridge, singleton)
    -> Orochi channel #telegram
    -> orochi-agent:master (receives via orochi-push channel subscription)
    -> replies via Orochi #telegram channel
    -> orochi-server (message hook intercepts)
    -> Telegram Bot API
    -> User

The orochi-server OWNS the Telegram bot token exclusively.  No other
process should poll the same bot.  The master agent communicates with
the user solely through the Orochi #telegram channel.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import aiohttp

from scitex_orochi._models import Message

if TYPE_CHECKING:
    from scitex_orochi._server import OrochiServer

log = logging.getLogger("orochi.telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramBridge:
    """Bi-directional relay between a Telegram chat and an Orochi channel.

    Incoming (Telegram -> Orochi):
      Telegram getUpdates -> post Message to self._channel with metadata
      containing chat_id, message_id, and telegram display name as sender.

    Outgoing (Orochi -> Telegram):
      Message hook fires on every channel message.  If the message is on
      self._channel and did NOT originate from Telegram (no echo), forward
      it to the Telegram chat via sendMessage.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        server: OrochiServer,
        *,
        channel: str = "#telegram",
        poll_timeout: int = 30,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._server = server
        self._channel = channel
        self._poll_timeout = poll_timeout

        self._offset: int = 0
        self._session: aiohttp.ClientSession | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._running = False
        self._bot_name: str = "unknown"

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Begin polling Telegram for updates."""
        self._session = aiohttp.ClientSession()
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())

        me = await self._api("getMe")
        self._bot_name = me.get("username", "unknown") if me else "unknown"
        log.info(
            "Telegram bridge active: @%s polling chat_id %s -> Orochi %s",
            self._bot_name,
            self._chat_id,
            self._channel,
        )

    async def stop(self) -> None:
        """Gracefully shut down polling and HTTP session."""
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        log.info("Telegram bridge stopped")

    # -- outgoing: Orochi -> Telegram ------------------------------------

    async def relay_to_telegram(self, msg: Message) -> None:
        """Send an Orochi channel message to the Telegram chat.

        Only messages on self._channel are forwarded.  Messages that
        originated from Telegram (metadata.source == "telegram") are
        skipped to prevent echo loops.
        """
        # Only relay messages posted to the telegram channel
        if msg.channel != self._channel:
            return

        # Avoid echo: skip messages that originated from Telegram
        metadata = msg.payload.get("metadata") or {}
        if metadata.get("source") == "telegram":
            return

        text = f"[{msg.sender}] {msg.content}"
        if not text.strip("[] "):
            return

        # Handle file attachments
        attachments = msg.payload.get("attachments") or []
        for att in attachments:
            url = att.get("url", "")
            if url:
                text += f"\n{url}"

        # If the Orochi message references a specific Telegram message_id,
        # reply to it in the Telegram chat.
        params: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
        }
        reply_to = metadata.get("reply_to_telegram_message_id")
        if reply_to:
            params["reply_to_message_id"] = reply_to

        result = await self._api("sendMessage", params)
        if result is None:
            log.error("Failed to relay message to Telegram from %s", msg.sender)

    # -- incoming: Telegram -> Orochi ------------------------------------

    async def _poll_loop(self) -> None:
        """Long-poll getUpdates and forward messages to Orochi."""
        while self._running:
            try:
                updates = await self._api(
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": self._poll_timeout,
                        "allowed_updates": ["message"],
                    },
                )
                if not updates:
                    continue
                for update in updates:
                    self._offset = update["update_id"] + 1
                    await self._process_update(update)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Telegram poll error, retrying in 5s")
                await asyncio.sleep(5)

    async def _process_update(self, update: dict[str, Any]) -> None:
        """Convert a Telegram update into an Orochi message on #telegram."""
        tg_msg = update.get("message")
        if not tg_msg:
            return

        # Only process messages from the configured chat
        msg_chat_id = str(tg_msg.get("chat", {}).get("id", ""))
        if msg_chat_id != str(self._chat_id):
            log.warning(
                "Ignoring Telegram message from unexpected chat_id=%s (expected %s)",
                msg_chat_id,
                self._chat_id,
            )
            return

        # Build sender display name
        user = tg_msg.get("from", {})
        display = user.get("first_name", "")
        username = user.get("username", "")
        if username:
            display = f"{display}(@{username})" if display else f"@{username}"
        sender = display or "telegram-user"

        # Extract text content
        content = tg_msg.get("text") or tg_msg.get("caption") or ""

        # Handle photo attachments
        attachments: list[dict[str, str]] = []
        photos = tg_msg.get("photo")
        if photos:
            # Telegram sends multiple sizes; pick the largest
            best = max(photos, key=lambda p: p.get("file_size", 0))
            file_id = best.get("file_id", "")
            if file_id:
                attachments.append({"type": "photo", "file_id": file_id})

        # Handle document attachments
        doc = tg_msg.get("document")
        if doc:
            attachments.append(
                {
                    "type": "document",
                    "file_id": doc.get("file_id", ""),
                    "filename": doc.get("file_name", "file"),
                }
            )

        # Handle voice messages
        voice = tg_msg.get("voice")
        if voice:
            attachments.append(
                {
                    "type": "voice",
                    "file_id": voice.get("file_id", ""),
                    "duration": voice.get("duration", 0),
                }
            )

        if not content and not attachments:
            return

        # Build metadata with Telegram-specific fields so the master agent
        # can reference original chat_id and message_id when replying.
        telegram_message_id = tg_msg.get("message_id")
        metadata: dict[str, Any] = {
            "source": "telegram",
            "telegram_user": sender,
            "telegram_chat_id": msg_chat_id,
            "telegram_message_id": telegram_message_id,
            "telegram_username": username,
        }

        payload: dict[str, Any] = {
            "channel": self._channel,
            "content": content,
            "metadata": metadata,
        }
        if attachments:
            payload["attachments"] = attachments

        msg = Message(
            type="message",
            sender=sender,
            payload=payload,
        )

        log.info(
            "[telegram->orochi] %s (msg_id=%s): %s",
            sender,
            telegram_message_id,
            content[:80],
        )
        await self._server._handle_message(msg)

    # -- Telegram Bot API helpers ----------------------------------------

    async def _api(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Call a Telegram Bot API method. Returns the 'result' field or None."""
        if not self._session:
            return None
        url = TELEGRAM_API.format(token=self._token, method=method)
        try:
            timeout = aiohttp.ClientTimeout(total=self._poll_timeout + 10)
            async with self._session.post(
                url, json=params or {}, timeout=timeout
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    log.error(
                        "Telegram API %s failed: %s", method, data.get("description")
                    )
                    return None
                return data.get("result")
        except asyncio.TimeoutError:
            log.warning("Telegram API %s timed out", method)
            return None
        except Exception:
            log.exception("Telegram API %s error", method)
            return None


async def setup_telegram_bridge(server: OrochiServer) -> TelegramBridge | None:
    """Create and start the Telegram bridge if configured.

    The bridge is a singleton: only ONE process should poll a given bot token.
    orochi-server owns this exclusively.

    Returns the bridge instance or None if not configured / missing credentials.
    """
    from scitex_orochi._config import (
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_BRIDGE_ENABLED,
        TELEGRAM_CHANNEL,
        TELEGRAM_CHAT_ID,
    )

    if not TELEGRAM_BRIDGE_ENABLED:
        log.info("Telegram bridge disabled (OROCHI_TELEGRAM_BRIDGE_ENABLED != true)")
        return None

    if not TELEGRAM_BOT_TOKEN:
        log.error(
            "Telegram bridge enabled but TELEGRAM_BOT_TOKEN is not set -- "
            "bridge will NOT start.  Set SCITEX_OROCHI_TELEGRAM_BOT_TOKEN or "
            "OROCHI_TELEGRAM_BOT_TOKEN env var."
        )
        return None

    if not TELEGRAM_CHAT_ID:
        log.error(
            "Telegram bridge enabled but TELEGRAM_CHAT_ID is not set -- "
            "bridge will NOT start.  Set SCITEX_OROCHI_TELEGRAM_CHAT_ID or "
            "OROCHI_TELEGRAM_CHAT_ID env var."
        )
        return None

    bridge = TelegramBridge(
        bot_token=TELEGRAM_BOT_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
        server=server,
        channel=TELEGRAM_CHANNEL,
    )

    # Ensure the #telegram channel exists in the server's channel registry
    server.channels.setdefault(TELEGRAM_CHANNEL, set())

    # Register the outgoing hook: Orochi #telegram -> Telegram chat
    server._message_hooks.append(bridge.relay_to_telegram)

    await bridge.start()
    return bridge
