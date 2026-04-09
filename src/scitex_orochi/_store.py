"""SQLite persistence layer for Orochi messages."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from scitex_orochi._config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id      TEXT NOT NULL,
    ts          TEXT NOT NULL,
    channel     TEXT NOT NULL,
    sender      TEXT NOT NULL,
    content     TEXT NOT NULL,
    mentions    TEXT,
    metadata    TEXT,
    sender_type TEXT NOT NULL DEFAULT 'human'
);

CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel);
CREATE INDEX IF NOT EXISTS idx_messages_sender  ON messages(sender);
CREATE INDEX IF NOT EXISTS idx_messages_ts      ON messages(ts);
"""

MIGRATE_SENDER_TYPE = """
ALTER TABLE messages ADD COLUMN sender_type TEXT NOT NULL DEFAULT 'human';
"""

BACKFILL_SENDER_TYPE = """
UPDATE messages SET sender_type = 'agent'
WHERE sender_type = 'human'
  AND (sender LIKE '%orochi-%' OR sender LIKE '%head-%');
"""


MAX_MESSAGES = 5000
PRUNE_INTERVAL = 100  # prune every N inserts


class MessageStore:
    """Async SQLite store for message persistence."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = str(db_path or DB_PATH)
        self._db: aiosqlite.Connection | None = None
        self._insert_count = 0

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        # Migrate existing DBs: add sender_type column if missing
        try:
            await self._db.execute(MIGRATE_SENDER_TYPE)
            await self._db.execute(BACKFILL_SENDER_TYPE)
            await self._db.commit()
        except Exception:
            pass  # Column already exists

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def save(
        self,
        msg_id: str,
        ts: str,
        channel: str,
        sender: str,
        content: str,
        mentions: list[str] | None = None,
        metadata: dict | None = None,
        sender_type: str = "human",
    ) -> None:
        if not self._db:
            raise RuntimeError("Store not open")
        await self._db.execute(
            "INSERT INTO messages (msg_id, ts, channel, sender, content, mentions, metadata, sender_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg_id,
                ts,
                channel,
                sender,
                content,
                json.dumps(mentions) if mentions else None,
                json.dumps(metadata) if metadata else None,
                sender_type,
            ),
        )
        await self._db.commit()

        # Periodic pruning to keep DB size bounded
        self._insert_count += 1
        if self._insert_count % PRUNE_INTERVAL == 0:
            await self._db.execute(
                "DELETE FROM messages WHERE id NOT IN "
                "(SELECT id FROM messages ORDER BY ts DESC LIMIT ?)",
                (MAX_MESSAGES,),
            )
            await self._db.commit()

    async def query(
        self,
        channel: str,
        since: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if not self._db:
            raise RuntimeError("Store not open")
        if since:
            cursor = await self._db.execute(
                "SELECT msg_id, ts, channel, sender, content, mentions, metadata, sender_type "
                "FROM messages WHERE channel = ? AND ts >= ? ORDER BY ts DESC LIMIT ?",
                (channel, since, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT msg_id, ts, channel, sender, content, mentions, metadata, sender_type "
                "FROM messages WHERE channel = ? ORDER BY ts DESC LIMIT ?",
                (channel, limit),
            )
        rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def recent(self, limit: int = 100) -> list[dict]:
        """Return the most recent messages across all channels."""
        if not self._db:
            raise RuntimeError("Store not open")
        cursor = await self._db.execute(
            "SELECT msg_id, ts, channel, sender, content, mentions, metadata, sender_type "
            "FROM messages ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        # Return in chronological order (oldest first)
        return [self._row_to_dict(r) for r in reversed(rows)]

    async def distinct_channels(self) -> list[str]:
        """Return all distinct channel names that have stored messages."""
        if not self._db:
            raise RuntimeError("Store not open")
        cursor = await self._db.execute(
            "SELECT DISTINCT channel FROM messages ORDER BY channel"
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _row_to_dict(r: tuple) -> dict:
        metadata = json.loads(r[6]) if r[6] else {}
        return {
            "msg_id": r[0],
            "ts": r[1],
            "channel": r[2],
            "sender": r[3],
            "content": r[4],
            "mentions": json.loads(r[5]) if r[5] else [],
            "metadata": metadata,
            "sender_type": r[7] if len(r) > 7 else "human",
            "attachments": metadata.get("attachments", []),
        }
