"""Resolve path to mcp_channel.ts for MCP config generation."""

from pathlib import Path


def get_push_server_path() -> str:
    """Return absolute path to mcp_channel.ts bundled with this package."""
    return str(Path(__file__).parent / "_ts" / "mcp_channel.ts")


def get_ts_dir() -> Path:
    """Return absolute path to the bundled _ts/ directory."""
    return Path(__file__).parent / "_ts"
