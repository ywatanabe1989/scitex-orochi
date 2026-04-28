"""Source-of-truth shapes for cross-cutting wire/registry data.

Module layout:

* ``_message.py`` — the WebSocket-frame ``Message`` dataclass used by
  the standalone-server clients (legacy single-file ``_models.py``,
  promoted to a package on 2026-04-28 so the heartbeat schema can
  live alongside it).
* ``heartbeat.py`` — canonical heartbeat field registry. See its
  docstring for the migration plan from the current 6-file
  duplication.
"""

from scitex_orochi._models._message import Message
from scitex_orochi._models.heartbeat import (
    HEARTBEAT_FIELD_NAMES,
    HEARTBEAT_FIELDS,
    HeartbeatField,
)

__all__ = [
    "HEARTBEAT_FIELDS",
    "HEARTBEAT_FIELD_NAMES",
    "HeartbeatField",
    "Message",
]
