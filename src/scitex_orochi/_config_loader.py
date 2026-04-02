"""Orochi deployment config loader -- reads orochi-config.yaml."""

from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Any

import yaml

# Search order for config file
CONFIG_SEARCH_PATHS = [
    Path("orochi-config.yaml"),
    Path("orochi-config.yml"),
    Path.home() / ".config" / "orochi" / "config.yaml",
    Path.home() / ".config" / "orochi" / "config.yml",
]


class ConfigError(Exception):
    """Raised when config is missing or invalid."""


def _default_user() -> str:
    """Return the current unix user, used when 'user' is omitted in config."""
    return getpass.getuser()


def build_agent_name(role: str, user: str, host: str) -> str:
    """Build an agent name in the colon convention.

    Format: orochi-agent:<role>:<user>@<host>
    Examples:
        orochi-agent:master:ywatanabe@ywata-note-win
        orochi-agent:head:ywatanabe@nas
        orochi-agent:sub:ywatanabe@nas:docker-build
    """
    return f"orochi-agent:{role}:{user}@{host}"


def parse_agent_name(name: str) -> dict[str, str]:
    """Parse a colon-convention agent name into components.

    Returns dict with keys: role, user, host.
    Raises ConfigError if format is invalid.
    """
    if not name.startswith("orochi-agent:"):
        raise ConfigError(f"Agent name must start with 'orochi-agent:', got: {name}")
    parts = name.split(":", 2)  # ["orochi-agent", "<role>", "<user>@<host>"]
    if len(parts) < 3:
        raise ConfigError(
            f"Agent name must have format orochi-agent:<role>:<user>@<host>, got: {name}"
        )
    role = parts[1]
    user_host = parts[2]
    if "@" not in user_host:
        raise ConfigError(
            f"Agent name must contain <user>@<host> after role, got: {name}"
        )
    user, host = user_host.split("@", 1)
    return {"role": role, "user": user, "host": host}


def find_config_path() -> Path | None:
    """Find orochi-config.yaml in search paths."""
    env_path = os.environ.get("OROCHI_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        return None
    for p in CONFIG_SEARCH_PATHS:
        if p.exists():
            return p
    return None


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load and validate orochi-config.yaml.

    Raises ConfigError if file not found or schema is invalid.
    """
    if path is None:
        path = find_config_path()
    if path is None:
        raise ConfigError(
            "orochi-config.yaml not found. "
            "Run 'scitex-orochi init' to create one, "
            "or set OROCHI_CONFIG env var."
        )
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ConfigError(f"Config must be a YAML mapping, got {type(raw).__name__}")

    orochi = raw.get("orochi")
    if orochi is None:
        raise ConfigError("Config missing top-level 'orochi' key")

    _validate_config(orochi)
    _inject_agent_names(orochi)
    return orochi


def _validate_config(cfg: dict[str, Any]) -> None:
    """Validate required config structure. Raises ConfigError on problems."""
    # Server section
    server = cfg.get("server")
    if not isinstance(server, dict):
        raise ConfigError("Config missing 'orochi.server' section")
    for key in ("host", "ws_port"):
        if key not in server:
            raise ConfigError(f"Config missing 'orochi.server.{key}'")

    # Master section
    master = cfg.get("master")
    if not isinstance(master, dict):
        raise ConfigError("Config missing 'orochi.master' section")
    if "host" not in master:
        raise ConfigError("Config missing 'orochi.master.host'")

    # Heads section (optional but must be list if present)
    heads = cfg.get("heads")
    if heads is not None:
        if not isinstance(heads, list):
            raise ConfigError("'orochi.heads' must be a list")
        for i, head in enumerate(heads):
            if not isinstance(head, dict):
                raise ConfigError(f"orochi.heads[{i}] must be a mapping")
            if "host" not in head:
                raise ConfigError(f"orochi.heads[{i}] missing 'host'")
            if "ssh" not in head:
                raise ConfigError(f"orochi.heads[{i}] missing 'ssh'")


def _inject_agent_names(cfg: dict[str, Any]) -> None:
    """Build and inject 'name' fields using the colon convention.

    Called after validation. Generates names from role + user + host.
    """
    default_user = _default_user()

    # Master
    master = cfg["master"]
    user = master.get("user", default_user)
    host = master["host"]
    master["name"] = build_agent_name("master", user, host)

    # Heads
    for head in cfg.get("heads", []):
        user = head.get("user", default_user)
        host = head["host"]
        head["name"] = build_agent_name("head", user, host)


def get_server_url(cfg: dict[str, Any]) -> str:
    """Return ws:// URL from config."""
    server = cfg["server"]
    host = server["host"]
    port = server["ws_port"]
    return f"ws://{host}:{port}"


def get_dashboard_url(cfg: dict[str, Any]) -> str:
    """Return dashboard URL from config."""
    server = cfg["server"]
    domain = server.get("domain")
    if domain:
        return f"https://{domain}"
    host = server["host"]
    port = server.get("dashboard_port", 8559)
    return f"http://{host}:{port}"


def render_template(template_str: str, variables: dict[str, Any]) -> str:
    """Render a template string with {variable} placeholders.

    Uses str.format_map with a defaulting dict to avoid KeyError on
    undefined variables (raises ConfigError instead).
    """

    class StrictDict(dict):
        def __missing__(self, key: str) -> str:
            raise ConfigError(f"Template variable not defined: {{{key}}}")

    return template_str.format_map(StrictDict(variables))


def build_template_vars(
    cfg: dict[str, Any], role: str, head_name: str | None = None
) -> dict[str, Any]:
    """Build template variables for CLAUDE.md rendering.

    Args:
        cfg: Loaded orochi config dict (the 'orochi' section).
        role: Either 'master' or 'head'.
        head_name: Required when role='head'.

    Returns:
        Dict of template variables.
    """
    server = cfg["server"]
    master = cfg["master"]

    base_vars = {
        "server_host": server["host"],
        "server_ws_port": server["ws_port"],
        "server_dashboard_port": server.get("dashboard_port", 8559),
        "server_domain": server.get("domain", ""),
        "server_url": get_server_url(cfg),
        "dashboard_url": get_dashboard_url(cfg),
    }

    if role == "master":
        base_vars.update(
            {
                "agent_name": master["name"],
                "agent_model": master.get("model", "opus[1m]"),
                "agent_channels": ", ".join(master.get("channels", ["#general"])),
                "agent_role": "master",
                "heads_list": _format_heads_list(cfg),
            }
        )
    elif role == "head":
        if head_name is None:
            raise ConfigError("head_name required for role='head'")
        head = _find_head(cfg, head_name)
        base_vars.update(
            {
                "agent_name": head["name"],
                "agent_model": head.get("model", "sonnet"),
                "agent_channels": ", ".join(head.get("channels", ["#general"])),
                "agent_role": "head",
                "agent_workdir": head.get("workdir", "~/proj"),
                "agent_host": head.get("host", head_name),
            }
        )
    else:
        raise ConfigError(f"Unknown role: {role}")

    return base_vars


def _find_head(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    """Find a head config by name, host, or full colon-convention name.

    Matches against:
      - Full name: orochi-agent:head:ywatanabe@nas
      - Host only: nas, server1
      - Legacy short name for backwards compatibility
    """
    for head in cfg.get("heads", []):
        head_name = head["name"]
        head_host = head.get("host", "")
        if name in (head_name, head_host):
            return head
        # Also try parsing the search name as a colon-convention name
        # and matching against host
        if name.startswith("orochi-agent:"):
            try:
                parsed = parse_agent_name(name)
                if parsed["host"] == head_host:
                    return head
            except ConfigError:
                pass
    available = [h["name"] for h in cfg.get("heads", [])]
    raise ConfigError(f"Head '{name}' not found in config. Available: {available}")


def _format_heads_list(cfg: dict[str, Any]) -> str:
    """Format heads as a readable list for master template."""
    heads = cfg.get("heads", [])
    if not heads:
        return "(no heads configured)"
    lines = []
    for h in heads:
        channels = ", ".join(h.get("channels", []))
        lines.append(
            f"- {h['name']} (model: {h.get('model', 'sonnet')}, channels: {channels})"
        )
    return "\n".join(lines)
