"""Orochi data models."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Message:
    type: str
    sender: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def channel(self) -> str:
        return self.payload.get("channel", "")

    @property
    def content(self) -> str:
        return self.payload.get("content", "")

    @property
    def mentions(self) -> list[str]:
        return re.findall(r"@([\w-]+)", self.content)

    def to_json(self) -> str:
        return json.dumps(
            {
                "type": self.type,
                "sender": self.sender,
                "payload": self.payload,
                "id": self.id,
                "ts": self.ts,
            }
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> Message:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        return cls(
            type=data["type"],
            sender=data.get("sender", "unknown"),
            payload=data.get("payload", {}),
            id=data.get("id", str(uuid.uuid4())),
            ts=data.get("ts", datetime.now(timezone.utc).isoformat()),
        )
