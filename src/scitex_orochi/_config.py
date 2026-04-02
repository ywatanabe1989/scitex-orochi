"""Orochi configuration -- environment-based settings."""

from __future__ import annotations

import os


def _env(new: str, old: str, default: str) -> str:
    """Check SCITEX_OROCHI_* first, fall back to OROCHI_*."""
    return os.environ.get(new) or os.environ.get(old, default)


HOST = _env("SCITEX_OROCHI_HOST", "OROCHI_HOST", "127.0.0.1")
PORT = int(_env("SCITEX_OROCHI_PORT", "OROCHI_PORT", "9559"))
DASHBOARD_PORT = int(
    _env("SCITEX_OROCHI_DASHBOARD_PORT", "OROCHI_DASHBOARD_PORT", "8559")
)
DB_PATH = _env("SCITEX_OROCHI_DB", "OROCHI_DB", "/data/orochi.db")
OROCHI_TOKEN = _env("SCITEX_OROCHI_TOKEN", "OROCHI_TOKEN", "")
GITEA_URL = _env("SCITEX_OROCHI_GITEA_URL", "OROCHI_GITEA_URL", "https://git.scitex.ai")
GITEA_TOKEN = _env("SCITEX_OROCHI_GITEA_TOKEN", "OROCHI_GITEA_TOKEN", "")
MEDIA_ROOT = _env("SCITEX_OROCHI_MEDIA_ROOT", "OROCHI_MEDIA_ROOT", "/data/orochi-media")
MEDIA_MAX_SIZE = int(
    _env("SCITEX_OROCHI_MEDIA_MAX_SIZE", "OROCHI_MEDIA_MAX_SIZE", str(20 * 1024 * 1024))
)

# Telegram bridge
TELEGRAM_BOT_TOKEN = _env(
    "SCITEX_OROCHI_TELEGRAM_BOT_TOKEN", "OROCHI_TELEGRAM_BOT_TOKEN", ""
)
TELEGRAM_CHAT_ID = _env("SCITEX_OROCHI_TELEGRAM_CHAT_ID", "OROCHI_TELEGRAM_CHAT_ID", "")
TELEGRAM_BRIDGE_ENABLED = _env(
    "SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED", "OROCHI_TELEGRAM_BRIDGE_ENABLED", "false"
).lower() in ("true", "1", "yes")
# Orochi channel that Telegram messages are posted to / read from
TELEGRAM_CHANNEL = _env(
    "SCITEX_OROCHI_TELEGRAM_CHANNEL", "OROCHI_TELEGRAM_CHANNEL", "#telegram"
)
