"""Shared helpers for CLI commands."""

from __future__ import annotations

import os
import platform
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scitex_orochi._client import OrochiClient

EXAMPLES_HEADER = "\nExamples:\n"


def get_agent_name() -> str:
    return os.environ.get("SCITEX_OROCHI_AGENT", platform.node())


def make_client(
    host: str,
    port: int,
    channels: list[str] | None = None,
    ws_path: str = "/ws/agent/",
) -> "OrochiClient":
    """Build an OrochiClient pointed at a Django Channels backend.

    ``ws_path`` defaults to ``/ws/agent/`` because that is the endpoint
    the Django Channels backend exposes. Omitting it (earlier versions
    of this helper did) caused the client to hit ``ws://host:port/``,
    which the server rejects with HTTP 500.
    """
    from scitex_orochi._client import OrochiClient

    return OrochiClient(
        name=get_agent_name(),
        host=host,
        port=port,
        channels=channels or ["#general"],
        ws_path=ws_path,
    )
