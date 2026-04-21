"""Environment + path resolution for the worker-progress daemon.

Keep this module side-effect free: callers decide when to mkdir / open
log files. The test suite imports these helpers directly.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

# WSS endpoint. Matches the hub-canonical URL used by
# scripts/client/check_connection.py (DEFAULT_WSS) and the bun MCP
# sidecar. Override with SCITEX_OROCHI_URL_WS if you're pointing at a
# dev hub — don't hard-code a fleet-wide override here.
DEFAULT_WSS = "wss://scitex-orochi.com"


def resolve_ws_url() -> str:
    """Return the WS base URL (without path/query)."""
    for key in ("SCITEX_OROCHI_URL_WS", "SCITEX_OROCHI_HUB_URL"):
        v = os.environ.get(key)
        if v:
            return v.rstrip("/")
    # Legacy HTTP-style env → upgrade to wss://
    http = os.environ.get("SCITEX_OROCHI_URL_HTTP", "").rstrip("/")
    if http.startswith("https://"):
        return "wss://" + http[len("https://") :]
    if http.startswith("http://"):
        return "ws://" + http[len("http://") :]
    return DEFAULT_WSS


def resolve_token() -> str:
    """Read the workspace token from env.

    Matches the env names used by scripts/client/agent_meta.py and
    fleet-watch/fleet_watch.sh. Both SCITEX_OROCHI_WORKSPACE_TOKEN and
    SCITEX_OROCHI_TOKEN are accepted; SCITEX_OROCHI_TOKEN wins if both
    are set (it is the historically canonical name).
    """
    for key in ("SCITEX_OROCHI_TOKEN", "SCITEX_OROCHI_WORKSPACE_TOKEN"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return ""


def default_log_path() -> Path:
    """Return the default log path for this OS.

    macOS: ``~/Library/Logs/scitex/worker-progress.log``
    Linux: ``~/.local/state/scitex/worker-progress.log``

    Windows / other: fall back to the Linux shape so the daemon at
    least logs somewhere deterministic.
    """
    home = Path(os.environ.get("HOME", str(Path.home())))
    if platform.system() == "Darwin":
        return home / "Library/Logs/scitex/worker-progress.log"
    # Linux / BSD / fallback
    state = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(state) if state else home / ".local/state"
    return base / "scitex/worker-progress.log"


def build_ws_uri(base_url: str, token: str, agent_name: str) -> str:
    """Compose the full ws URL that ``hub/routing.py`` expects.

    Trailing slash matters: routing is ``re_path(r"ws/agent/$", ...)``.
    """
    base = base_url.rstrip("/")
    return f"{base}/ws/agent/?token={token}&agent={agent_name}"
