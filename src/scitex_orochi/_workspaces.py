"""Workspace model -- organizes channels into named groups."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

log = logging.getLogger("orochi.workspaces")

WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    settings    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS workspace_channels (
    workspace_id TEXT NOT NULL,
    channel      TEXT NOT NULL,
    PRIMARY KEY (workspace_id, channel),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id TEXT NOT NULL,
    agent_name   TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'member',
    joined_at    TEXT NOT NULL,
    PRIMARY KEY (workspace_id, agent_name),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workspace_invites (
    token        TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'member',
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT,
    max_uses     INTEGER DEFAULT 0,
    use_count    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workspace_tokens (
    token        TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
"""

DEFAULT_WORKSPACE_NAME = "default"


@dataclass
class Workspace:
    id: str
    name: str
    description: str = ""
    channels: list[str] = field(default_factory=list)
    members: dict[str, str] = field(default_factory=dict)  # agent_name -> role
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "channels": self.channels,
            "members": self.members,
            "settings": self.settings,
            "created_at": self.created_at,
        }


class WorkspaceStore:
    """Persistent workspace storage backed by SQLite."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def init_schema(self) -> None:
        await self._db.executescript(WORKSPACE_SCHEMA)
        await self._db.commit()
        # Ensure default workspace exists
        await self._ensure_default()

    async def _ensure_default(self) -> None:
        cursor = await self._db.execute(
            "SELECT id FROM workspaces WHERE name = ?",
            (DEFAULT_WORKSPACE_NAME,),
        )
        row = await cursor.fetchone()
        if not row:
            from datetime import datetime, timezone

            ws_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "INSERT INTO workspaces (id, name, description, created_at) "
                "VALUES (?, ?, ?, ?)",
                (ws_id, DEFAULT_WORKSPACE_NAME, "Default workspace", now),
            )
            # Add #general to default workspace
            await self._db.execute(
                "INSERT INTO workspace_channels (workspace_id, channel) VALUES (?, ?)",
                (ws_id, "#general"),
            )
            await self._db.commit()
            log.info("Created default workspace %s", ws_id)

    async def list_workspaces(self) -> list[Workspace]:
        cursor = await self._db.execute(
            "SELECT id, name, description, created_at, settings FROM workspaces ORDER BY name"
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            ws = Workspace(
                id=r[0],
                name=r[1],
                description=r[2],
                created_at=r[3],
                settings=json.loads(r[4]) if r[4] else {},
            )
            ws.channels = await self._get_channels(ws.id)
            ws.members = await self._get_members(ws.id)
            result.append(ws)
        return result

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        cursor = await self._db.execute(
            "SELECT id, name, description, created_at, settings FROM workspaces WHERE id = ?",
            (workspace_id,),
        )
        r = await cursor.fetchone()
        if not r:
            return None
        ws = Workspace(
            id=r[0],
            name=r[1],
            description=r[2],
            created_at=r[3],
            settings=json.loads(r[4]) if r[4] else {},
        )
        ws.channels = await self._get_channels(ws.id)
        ws.members = await self._get_members(ws.id)
        return ws

    async def create_workspace(
        self,
        name: str,
        description: str = "",
        channels: list[str] | None = None,
    ) -> Workspace:
        from datetime import datetime, timezone

        ws_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO workspaces (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (ws_id, name, description, now),
        )
        for ch in channels or []:
            await self._db.execute(
                "INSERT OR IGNORE INTO workspace_channels (workspace_id, channel) VALUES (?, ?)",
                (ws_id, ch),
            )
        await self._db.commit()
        log.info("Created workspace %s (%s)", name, ws_id)
        return await self.get_workspace(ws_id)  # type: ignore[return-value]

    async def delete_workspace(self, workspace_id: str) -> bool:
        # Prevent deleting the default workspace
        cursor = await self._db.execute(
            "SELECT name FROM workspaces WHERE id = ?", (workspace_id,)
        )
        row = await cursor.fetchone()
        if not row or row[0] == DEFAULT_WORKSPACE_NAME:
            return False
        await self._db.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        await self._db.commit()
        return True

    async def add_channel(self, workspace_id: str, channel: str) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO workspace_channels (workspace_id, channel) VALUES (?, ?)",
            (workspace_id, channel),
        )
        await self._db.commit()

    async def remove_channel(self, workspace_id: str, channel: str) -> None:
        await self._db.execute(
            "DELETE FROM workspace_channels WHERE workspace_id = ? AND channel = ?",
            (workspace_id, channel),
        )
        await self._db.commit()

    async def add_member(
        self, workspace_id: str, agent_name: str, role: str = "member"
    ) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT OR REPLACE INTO workspace_members (workspace_id, agent_name, role, joined_at) "
            "VALUES (?, ?, ?, ?)",
            (workspace_id, agent_name, role, now),
        )
        await self._db.commit()

    async def remove_member(self, workspace_id: str, agent_name: str) -> None:
        await self._db.execute(
            "DELETE FROM workspace_members WHERE workspace_id = ? AND agent_name = ?",
            (workspace_id, agent_name),
        )
        await self._db.commit()

    async def _get_channels(self, workspace_id: str) -> list[str]:
        cursor = await self._db.execute(
            "SELECT channel FROM workspace_channels WHERE workspace_id = ? ORDER BY channel",
            (workspace_id,),
        )
        return [r[0] for r in await cursor.fetchall()]

    async def _get_members(self, workspace_id: str) -> dict[str, str]:
        cursor = await self._db.execute(
            "SELECT agent_name, role FROM workspace_members WHERE workspace_id = ?",
            (workspace_id,),
        )
        return {r[0]: r[1] for r in await cursor.fetchall()}

    # -- Invitations -------------------------------------------------------

    async def create_invite(
        self,
        workspace_id: str,
        created_by: str,
        role: str = "member",
        max_uses: int = 0,
        expires_hours: int = 0,
    ) -> dict[str, Any]:
        """Create an invitation token for a workspace.

        Args:
            max_uses: 0 means unlimited.
            expires_hours: 0 means never expires.
        """
        from datetime import datetime, timedelta, timezone

        token = uuid.uuid4().hex[:16]
        now = datetime.now(timezone.utc)
        expires_at = (
            (now + timedelta(hours=expires_hours)).isoformat()
            if expires_hours > 0
            else None
        )
        await self._db.execute(
            "INSERT INTO workspace_invites "
            "(token, workspace_id, role, created_by, created_at, expires_at, max_uses) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                workspace_id,
                role,
                created_by,
                now.isoformat(),
                expires_at,
                max_uses,
            ),
        )
        await self._db.commit()
        log.info(
            "Created invite %s for workspace %s by %s", token, workspace_id, created_by
        )
        return {
            "token": token,
            "workspace_id": workspace_id,
            "role": role,
            "expires_at": expires_at,
            "max_uses": max_uses,
        }

    async def redeem_invite(self, token: str, agent_name: str) -> dict[str, Any] | None:
        """Redeem an invitation token. Returns workspace info or None if invalid."""
        from datetime import datetime, timezone

        cursor = await self._db.execute(
            "SELECT workspace_id, role, expires_at, max_uses, use_count "
            "FROM workspace_invites WHERE token = ?",
            (token,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        workspace_id, role, expires_at, max_uses, use_count = row

        # Check expiry
        if expires_at:
            exp = datetime.fromisoformat(expires_at)
            if datetime.now(timezone.utc) > exp:
                return None

        # Check max uses
        if max_uses > 0 and use_count >= max_uses:
            return None

        # Add member and increment use count
        await self.add_member(workspace_id, agent_name, role)
        await self._db.execute(
            "UPDATE workspace_invites SET use_count = use_count + 1 WHERE token = ?",
            (token,),
        )
        await self._db.commit()

        ws = await self.get_workspace(workspace_id)
        log.info(
            "Agent %s joined workspace %s via invite %s",
            agent_name,
            workspace_id,
            token,
        )
        return ws.to_dict() if ws else None

    async def list_invites(self, workspace_id: str) -> list[dict[str, Any]]:
        """List active invitations for a workspace."""
        cursor = await self._db.execute(
            "SELECT token, role, created_by, created_at, expires_at, max_uses, use_count "
            "FROM workspace_invites WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "token": r[0],
                "role": r[1],
                "created_by": r[2],
                "created_at": r[3],
                "expires_at": r[4],
                "max_uses": r[5],
                "use_count": r[6],
            }
            for r in rows
        ]

    async def revoke_invite(self, token: str) -> bool:
        """Revoke an invitation token."""
        cursor = await self._db.execute(
            "DELETE FROM workspace_invites WHERE token = ?", (token,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    # ── Workspace tokens (agent auth) ───────────────────────────

    async def create_workspace_token(self, workspace_id: str, label: str = "") -> dict:
        """Generate a token that grants access to a workspace."""
        from datetime import datetime, timezone

        token = "wks_" + uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO workspace_tokens (token, workspace_id, label, created_at) "
            "VALUES (?, ?, ?, ?)",
            (token, workspace_id, label, now),
        )
        await self._db.commit()
        log.info("Created workspace token for %s (label=%s)", workspace_id, label)
        return {
            "token": token,
            "workspace_id": workspace_id,
            "label": label,
            "created_at": now,
        }

    async def resolve_token(self, token: str) -> str | None:
        """Resolve a workspace token to its workspace_id. Returns None if invalid."""
        cursor = await self._db.execute(
            "SELECT workspace_id FROM workspace_tokens WHERE token = ?",
            (token,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def list_workspace_tokens(self, workspace_id: str) -> list[dict]:
        """List all tokens for a workspace."""
        cursor = await self._db.execute(
            "SELECT token, label, created_at "
            "FROM workspace_tokens WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        )
        rows = await cursor.fetchall()
        return [{"token": r[0], "label": r[1], "created_at": r[2]} for r in rows]

    async def revoke_workspace_token(self, token: str) -> bool:
        """Revoke a workspace token."""
        cursor = await self._db.execute(
            "DELETE FROM workspace_tokens WHERE token = ?", (token,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def ensure_default_token(self) -> str:
        """Ensure the default workspace has at least one token. Returns it."""
        cursor = await self._db.execute(
            "SELECT w.id FROM workspaces w WHERE w.name = ?",
            (DEFAULT_WORKSPACE_NAME,),
        )
        row = await cursor.fetchone()
        if not row:
            await self._ensure_default()
            return await self.ensure_default_token()
        ws_id = row[0]
        tokens = await self.list_workspace_tokens(ws_id)
        if tokens:
            return tokens[0]["token"]
        result = await self.create_workspace_token(ws_id, label="default")
        return result["token"]
