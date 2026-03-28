"""Backward-compatibility shim -- use scitex_orochi._config instead."""

from scitex_orochi._config import (
    DB_PATH,
    DASHBOARD_PORT,
    GITEA_TOKEN,
    GITEA_URL,
    HOST,
    OROCHI_TOKEN,
    PORT,
)

__all__ = [
    "HOST",
    "PORT",
    "DASHBOARD_PORT",
    "DB_PATH",
    "OROCHI_TOKEN",
    "GITEA_URL",
    "GITEA_TOKEN",
]
