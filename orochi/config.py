"""Orochi configuration."""

import os
from pathlib import Path

HOST = os.environ.get("OROCHI_HOST", "127.0.0.1")
PORT = int(os.environ.get("OROCHI_PORT", "9559"))
DASHBOARD_PORT = int(os.environ.get("OROCHI_DASHBOARD_PORT", "8559"))
DB_PATH = Path(os.environ.get("OROCHI_DB", Path(__file__).parent.parent / "orochi.db"))
OROCHI_TOKEN = os.environ.get("OROCHI_TOKEN", "")
GITEA_URL = os.environ.get("GITEA_URL", "http://localhost:3000")
GITEA_TOKEN = os.environ.get("GITEA_TOKEN", "")
