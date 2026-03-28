"""Message data models for Orochi."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


MENTION_RE = re.compile(r"@([\w\-]+)")


@dataclass
class Message:
    type: str
    sender: str
    payload: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> Message:
        data = json.loads(raw)
        return cls(
            type=data["type"],
            sender=data.get("sender", "unknown"),
            payload=data.get("payload", {}),
            id=data.get("id", str(uuid.uuid4())),
            ts=data.get("ts", datetime.now(timezone.utc).isoformat()),
        )

    @property
    def channel(self) -> str | None:
        return self.payload.get("channel")

    @property
    def content(self) -> str:
        return self.payload.get("content", "")

    @property
    def mentions(self) -> list[str]:
        explicit = self.payload.get("mentions", [])
        if explicit:
            return explicit
        return MENTION_RE.findall(self.content)
