"""Orochi MCP config builder (moved from scitex_agent_container.runtimes.orochi_mcp).

Generates the JSON file that Claude Code loads via ``--mcp-config`` when an
agent needs to speak to the Orochi hub through the TypeScript MCP bridge
(``mcp_channel.ts``).

Design note: this module used to live in scitex-agent-container and was
called from its claude_code orochi_runtime. That was an SoC violation —
scitex-agent-container is a generic lifecycle library and should not know
about Orochi hosts, tokens, or channel shapes. As of the dispatch refactor,
scitex-orochi owns this logic and passes the resulting file path to
agent-container via a shim yaml's ``claude.flags`` list.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from .spec import OrochiSpec

logger = logging.getLogger("scitex-orochi.bridge.mcp")


def find_mcp_channel_ts(explicit_path: str = "") -> str | None:
    """Resolve the path to scitex-orochi's ``mcp_channel.ts``.

    Priority:
      0. Explicit ``spec.orochi.ts_path`` from the agent yaml
      1. ``SCITEX_OROCHI_PUSH_TS`` environment variable
      2. Relative to the ``scitex_orochi`` Python package (dev installs)
      3. Well-known path ``/opt/scitex-orochi/ts/mcp_channel.ts``
    """
    if explicit_path:
        p = Path(explicit_path).expanduser()
        if p.is_file():
            return str(p)
        logger.warning("spec.orochi.ts_path is set but not found: %s", p)

    env_path = os.environ.get("SCITEX_OROCHI_PUSH_TS", "")
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_file():
            return str(p)

    # Resolve from the installed scitex_orochi package (dev install layout:
    # src/scitex_orochi/__init__.py -> ../../ts/mcp_channel.ts).
    try:
        import scitex_orochi

        pkg_file = Path(scitex_orochi.__file__ or "")
        candidate = pkg_file.parent.parent.parent / "ts" / "mcp_channel.ts"
        if candidate.is_file():
            return str(candidate)
    except Exception:
        pass

    system_path = Path("/opt/scitex-orochi/ts/mcp_channel.ts")
    if system_path.is_file():
        return str(system_path)

    return None


def _resolve_token(orochi: OrochiSpec, agent_env: dict[str, str]) -> str:
    """Resolve the Orochi workspace token.

    Lookup order:
      1. Agent's own yaml ``spec.env`` dict (explicit per-agent override)
      2. Current shell's ``os.environ``
      3. A fresh ``bash -l -c`` subprocess (for callers whose non-interactive
         shell hasn't sourced the secrets file)

    Returns an empty string if the token cannot be found. A missing token
    is still a launchable state — the sidecar/MCP client will fail to auth
    at orochi_runtime and log a clear error, which is better than refusing to
    generate the config at all.
    """
    token = agent_env.get(orochi.token_env, "")
    if token:
        return token

    token = os.environ.get(orochi.token_env, "")
    if token:
        return token

    # Fall back to a login shell so ~/.bash_profile (and transitively the
    # secrets file that exports SCITEX_OROCHI_TOKEN) gets sourced.
    try:
        result = subprocess.run(
            ["bash", "-l", "-c", f"echo ${orochi.token_env}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        token = result.stdout.strip()
        if token:
            logger.info("Resolved %s via bash login shell fallback", orochi.token_env)
            return token
    except Exception as exc:
        logger.debug("bash -l token lookup failed: %s", exc)

    return ""


def build_orochi_mcp_config(
    *,
    agent_name: str,
    orochi: OrochiSpec,
    agent_env: dict[str, str],
    agent_labels: dict[str, str],
) -> dict | None:
    """Build the MCP server config dict for scitex-orochi.

    Returns None if Orochi is not enabled or the ts bridge file cannot
    be located.
    """
    if not orochi.is_enabled:
        return None

    ts_path = find_mcp_channel_ts(orochi.ts_path)
    if ts_path is None:
        logger.warning(
            "Orochi enabled but mcp_channel.ts not found. "
            "Set SCITEX_OROCHI_PUSH_TS env var or install scitex-orochi."
        )
        return None

    host = orochi.hosts[0] if orochi.hosts else "localhost"

    # Channel subscriptions are server-authoritative: assigned at orochi_runtime via
    # MCP tools, REST API, or web UI. The agent registers with no channels;
    # the server hydrates memberships from persisted state.
    token = _resolve_token(orochi, agent_env)

    env_block: dict[str, str] = {
        "SCITEX_OROCHI_HOST": host,
        "SCITEX_OROCHI_PORT": str(orochi.port),
        "SCITEX_OROCHI_AGENT": agent_name,
        # Defuse mcp_channel.ts's telegram-guard when the parent shell has
        # a telegram bot token in env (e.g., launched from a telegrammer
        # shell). Empty string is falsy, so the guard passes harmlessly.
        "SCITEX_OROCHI_TELEGRAM_BOT_TOKEN": "",
        "SCITEX_OROCHI_AGENT_ROLE": "",
    }
    if token:
        env_block["SCITEX_OROCHI_TOKEN"] = token

    icon_image = agent_labels.get("icon-image", "")
    icon_emoji = agent_labels.get("icon-emoji", "")
    icon_text = agent_labels.get("icon-text", "")
    icon = (
        icon_image
        or icon_emoji
        or agent_labels.get("icon", "")
        or agent_env.get("SCITEX_OROCHI_ICON", "")
    )
    if icon:
        env_block["SCITEX_OROCHI_ICON"] = icon
    if icon_emoji:
        env_block["SCITEX_OROCHI_ICON_EMOJI"] = icon_emoji
    if icon_text:
        env_block["SCITEX_OROCHI_ICON_TEXT"] = icon_text

    return {
        "mcpServers": {
            "scitex-orochi": {
                "type": "stdio",
                "command": "bun",
                "args": [ts_path],
                "env": env_block,
            }
        }
    }


def write_mcp_config_file(
    *,
    agent_name: str,
    orochi: OrochiSpec,
    agent_env: dict[str, str],
    agent_labels: dict[str, str],
) -> str | None:
    """Generate the MCP config JSON file and return its path.

    The file lives under ``/tmp/scitex-orochi/mcp-configs/`` so the same
    absolute path is valid on every host (Linux ``/home/<user>``, macOS
    ``/Users/<user>``, etc.). The bridge then scp's this file to the
    remote at the *same* path before claude starts there, so the
    ``--mcp-config`` flag in the shim yaml is portable.

    Returns None if Orochi is not enabled (the caller should skip the
    ``--mcp-config`` flag entirely in that case).
    """
    mcp_config = build_orochi_mcp_config(
        agent_name=agent_name,
        orochi=orochi,
        agent_env=agent_env,
        agent_labels=agent_labels,
    )
    if mcp_config is None:
        return None

    config_dir = Path("/tmp/scitex-orochi/mcp-configs")
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"mcp-{agent_name}.json"

    config_path.write_text(json.dumps(mcp_config, indent=2) + "\n")
    logger.info(
        "Orochi MCP config written to %s (agent=%s, host=%s)",
        config_path,
        agent_name,
        mcp_config["mcpServers"]["scitex-orochi"]["env"]["SCITEX_OROCHI_HOST"],
    )
    return str(config_path)
