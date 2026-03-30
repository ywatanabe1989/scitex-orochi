"""Telegram Bridge -- relay messages between Orochi and Telegram Bot API."""

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
    """Bi-directional relay between a Telegram chat and Orochi channels."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        server: OrochiServer,
        *,
        channel: str = "#general",
        sender_name: str = "telegram-user",
        poll_timeout: int = 30,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._server = server
        self._channel = channel
        self._sender_name = sender_name
        self._poll_timeout = poll_timeout

        self._offset: int = 0
        self._session: aiohttp.ClientSession | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._running = False

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Begin polling Telegram for updates."""
        self._session = aiohttp.ClientSession()
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        me = await self._api("getMe")
        bot_name = me.get("username", "unknown") if me else "unknown"
        log.info(
            "Telegram bridge started (bot=@%s, chat=%s, channel=%s)",
            bot_name,
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
        """Send an Orochi channel message to the Telegram chat."""
        # Avoid echo: skip messages that originated from Telegram
        metadata = msg.payload.get("metadata") or {}
        if metadata.get("source") == "telegram":
            return

        text = f"[{msg.sender}] {msg.content}"
        if not text.strip("[] "):
            return

        # Handle file attachments
        attachments = msg.payload.get("attachments") or []
        if attachments:
            for att in attachments:
                url = att.get("url", "")
                if url:
                    text += f"\n📎 {url}"

        await self._api(
            "sendMessage",
            {
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
        )

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
        """Convert a Telegram update into an Orochi message."""
        tg_msg = update.get("message")
        if not tg_msg:
            return

        # Build sender display name
        user = tg_msg.get("from", {})
        display = user.get("first_name", "")
        username = user.get("username", "")
        if username:
            display = f"{display}(@{username})" if display else f"@{username}"
        sender = display or self._sender_name

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

        if not content and not attachments:
            return

        payload: dict[str, Any] = {
            "channel": self._channel,
            "content": content,
        }
        if attachments:
            payload["attachments"] = attachments
        payload["metadata"] = {"source": "telegram", "telegram_user": sender}

        msg = Message(
            type="message",
            sender=sender,
            payload=payload,
        )

        log.info("[telegram->orochi] %s: %s", sender, content[:80])
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
    """Create and start the Telegram bridge if configured. Returns bridge or None."""
    from scitex_orochi._config import (
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_BRIDGE_ENABLED,
        TELEGRAM_CHAT_ID,
    )

    if not TELEGRAM_BRIDGE_ENABLED or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        if TELEGRAM_BRIDGE_ENABLED:
            log.warning("Telegram bridge enabled but BOT_TOKEN or CHAT_ID not set")
        return None
    bridge = TelegramBridge(
        bot_token=TELEGRAM_BOT_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
        server=server,
    )
    server._message_hooks.append(bridge.relay_to_telegram)
    await bridge.start()
    return bridge
