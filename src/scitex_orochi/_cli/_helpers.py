"""Shared helpers for CLI commands."""

from __future__ import annotations

import os
import platform

EXAMPLES_HEADER = "\nExamples:\n"


def get_agent_name() -> str:
    return os.environ.get("SCITEX_OROCHI_AGENT", platform.node())


def make_client(
    host: str, port: int, channels: list[str] | None = None
) -> "OrochiClient":
    from scitex_orochi._client import OrochiClient

    return OrochiClient(
        name=get_agent_name(),
        host=host,
        port=port,
        channels=channels or ["#general"],
    )
