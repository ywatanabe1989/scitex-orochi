"""Orochi configuration -- environment-based settings."""

from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    """Read SCITEX_OROCHI_* environment variable."""
    return os.environ.get(name, default)


HOST = _env("SCITEX_OROCHI_HOST", "127.0.0.1")
PORT = int(_env("SCITEX_OROCHI_PORT", "9559"))
DASHBOARD_PORT = int(_env("SCITEX_OROCHI_DASHBOARD_PORT", "8559"))
DB_PATH = _env("SCITEX_OROCHI_DB", "/data/orochi.db")
ADMIN_TOKEN = _env("SCITEX_OROCHI_ADMIN_TOKEN", "")
# Backward compat: SCITEX_OROCHI_TOKEN acts as admin token if ADMIN_TOKEN not set
if not ADMIN_TOKEN:
    ADMIN_TOKEN = _env("SCITEX_OROCHI_TOKEN", "")
OROCHI_TOKEN = ADMIN_TOKEN  # alias used by existing code
GITEA_URL = _env("SCITEX_OROCHI_GITEA_URL", "https://git.scitex.ai")
GITEA_TOKEN = _env("SCITEX_OROCHI_GITEA_TOKEN", "")
MEDIA_ROOT = _env("SCITEX_OROCHI_MEDIA_ROOT", "/data/orochi-media")
MEDIA_MAX_SIZE = int(_env("SCITEX_OROCHI_MEDIA_MAX_SIZE", str(20 * 1024 * 1024)))

# Dashboard WebSocket upstream (for dev -> stable sync)
# When set, the dashboard JS connects to this URL instead of its own host.
# Example: "wss://orochi.scitex.ai" makes dev dashboard observe stable's feed.
DASHBOARD_WS_UPSTREAM = _env("SCITEX_OROCHI_DASHBOARD_WS_UPSTREAM", "")

# CORS: comma-separated origins allowed to call /api/* (for dev -> stable sync)
# Example: "https://orochi-dev.scitex.ai"
CORS_ORIGINS = _env("SCITEX_OROCHI_CORS_ORIGINS", "")

# Telegram bridge
TELEGRAM_BOT_TOKEN = _env("SCITEX_OROCHI_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env("SCITEX_OROCHI_TELEGRAM_CHAT_ID", "")
TELEGRAM_BRIDGE_ENABLED = _env(
    "SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED", "false"
).lower() in ("true", "1", "yes")
# Orochi channel that Telegram messages are posted to / read from
TELEGRAM_CHANNEL = _env("SCITEX_OROCHI_TELEGRAM_CHANNEL", "#telegram")
