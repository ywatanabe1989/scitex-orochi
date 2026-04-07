"""Resolve path to orochi_push.ts for MCP config generation."""

from pathlib import Path


def get_push_server_path() -> str:
    """Return absolute path to orochi_push.ts bundled with this package."""
    return str(Path(__file__).parent / "_ts" / "orochi_push.ts")


def get_ts_dir() -> Path:
    """Return absolute path to the bundled _ts/ directory."""
    return Path(__file__).parent / "_ts"
