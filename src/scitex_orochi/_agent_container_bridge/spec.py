"""OrochiSpec — parsed ``spec.orochi:`` section of an agent yaml.

Previously lived in ``scitex_agent_container.config`` as a first-class
field of ``AgentConfig``. Moved here as part of the SoC refactor:
scitex-agent-container is now a generic lifecycle library with zero
Orochi knowledge, and scitex-orochi loads this section itself from the
raw yaml before dispatching to agent-container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class OrochiSpec:
    enabled: bool = False
    # Tried in order (first reachable wins).
    hosts: list[str] = field(default_factory=list)
    # Django Channels default (HTTP + WS unified).
    port: int = 8559
    ws_path: str = "/ws/agent/"
    # Env var holding the auth token.
    token_env: str = "SCITEX_OROCHI_TOKEN"
    # Channels to subscribe on startup.
    channels: list[str] = field(default_factory=list)
    heartbeat_interval: int = 30
    reconnect_interval: int = 10
    # 0 = infinite.
    reconnect_max_retries: int = 0
    # Explicit path to mcp_channel.ts (overrides auto-detection).
    ts_path: str = ""

    @property
    def is_enabled(self) -> bool:
        """Return True if Orochi auto-connect is configured."""
        return self.enabled and len(self.hosts) > 0


def load_orochi_spec(yaml_path: str | Path) -> OrochiSpec:
    """Parse the ``spec.orochi:`` section from an agent yaml file.

    Returns a default (disabled) OrochiSpec if the section is missing.
    Supports both ``hosts: [a, b]`` and legacy ``host: a`` forms.
    """
    with open(yaml_path) as f:
        raw = yaml.safe_load(f) or {}

    spec_raw = raw.get("spec", {}) or {}
    orochi_raw = spec_raw.get("orochi", {}) or {}

    hosts = orochi_raw.get("hosts", []) or []
    if not hosts:
        single = orochi_raw.get("host", "")
        if single:
            hosts = [single]

    return OrochiSpec(
        enabled=orochi_raw.get("enabled", False),
        hosts=hosts,
        port=int(orochi_raw.get("port", 8559)),
        ws_path=orochi_raw.get("ws_path", "/ws/agent/"),
        token_env=orochi_raw.get("token_env", "SCITEX_OROCHI_TOKEN"),
        channels=orochi_raw.get("channels", []) or [],
        heartbeat_interval=int(orochi_raw.get("heartbeat_interval", 30)),
        reconnect_interval=int(orochi_raw.get("reconnect_interval", 10)),
        reconnect_max_retries=int(orochi_raw.get("reconnect_max_retries", 0)),
        ts_path=orochi_raw.get("ts_path", ""),
    )
