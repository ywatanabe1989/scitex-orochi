"""Helper functions for launch commands: resolution, legacy fallback."""

from __future__ import annotations

import importlib.resources
import json
import subprocess
import sys
from pathlib import Path

import click

from scitex_orochi._config_loader import (
    ConfigError,
    _find_head,
    build_template_vars,
    load_config,
    render_template,
)

# Optional scitex-agent-container integration
try:
    from scitex_agent_container import agent_start as _ac_agent_start

    HAS_AGENT_CONTAINER = True
except ImportError:
    HAS_AGENT_CONTAINER = False

# Default agents directory (relative to project root / cwd)
# The repo ships example definitions under examples/agents/; real configs
# live in ~/.scitex/orochi/agents/ (USER_AGENTS_DIR) and are checked first.
DEFAULT_AGENTS_DIR = Path("examples/agents")
USER_AGENTS_DIR = Path.home() / ".scitex" / "orochi" / "agents"


def find_agent_yaml(name: str, agents_dir: Path | None = None) -> Path | None:
    """Resolve an agent YAML file by convention.

    Given a short role name like "master", "head", "mamba", or a more
    specific "head-mba", find the agent yaml file to launch.

    Search order (first hit wins):
      1. ``~/.scitex/orochi/agents/<name>.yaml`` (flat file)
      2. ``~/.scitex/orochi/agents/<name>/<name>.yaml`` (dir-per-agent)
      3. ``~/.scitex/orochi/agents/head-<name>/head-<name>.yaml``
         (dir-per-agent with "head-" prefix, e.g. ``head-mba``)
      4. ``~/.scitex/orochi/agents/<name>-*/` — machine-suffix convention,
         e.g. ``master`` resolves to ``master-ywata-note-win`` if that is
         the only matching directory. If multiple matches exist, returns
         None (ambiguous — caller should use --agent-config explicitly).
      5. Repo fallback: ``examples/agents/{name,head-<name>}.{yaml,yml}``

    Returns the resolved Path or None if not found.
    """
    # Check user config dir first (flat files + subdirectory convention)
    if USER_AGENTS_DIR.is_dir():
        for ext in (".yaml", ".yml"):
            for prefix in ("", "head-"):
                prefixed = f"{prefix}{name}"
                for candidate in (
                    USER_AGENTS_DIR / f"{prefixed}{ext}",
                    USER_AGENTS_DIR / name / f"{prefixed}{ext}",
                    # dir-per-agent with prefix applied to both dir and
                    # file, e.g. head-nas/head-nas.yaml
                    USER_AGENTS_DIR / prefixed / f"{prefixed}{ext}",
                ):
                    if candidate.exists():
                        return candidate

        # Machine-suffix convention: resolve ``master`` to the
        # unambiguous ``master-*/master-*.yaml``, ``mamba`` to
        # ``mamba-*/mamba-*.yaml``, etc. Only match at the start of the
        # directory name, and only if exactly one directory matches.
        matches: list[Path] = []
        for sub in sorted(USER_AGENTS_DIR.iterdir()):
            if not sub.is_dir():
                continue
            if sub.name == "legacy" or sub.name.startswith("_"):
                continue
            if not (sub.name == name or sub.name.startswith(f"{name}-")):
                continue
            for ext in (".yaml", ".yml"):
                candidate = sub / f"{sub.name}{ext}"
                if candidate.exists():
                    matches.append(candidate)
                    break
        if len(matches) == 1:
            return matches[0]

    # Fall back to repo agents/ dir
    d = (agents_dir or DEFAULT_AGENTS_DIR).resolve()
    if not d.is_dir():
        return None

    candidates = [
        d / f"{name}.yaml",
        d / f"{name}.yml",
        d / f"head-{name}.yaml",
        d / f"head-{name}.yml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def find_all_agent_yamls(agents_dir: Path | None = None) -> list[Path]:
    """Find all agent YAML files in the agents directory.

    Prefers the user config dir (~/.scitex/orochi/agents/) when it exists,
    otherwise falls back to the repo ``examples/agents/`` directory.

    Walks one level deep to support the dir-per-agent layout
    (e.g. ``mamba/mamba.yaml``). Excludes:
      - files whose names start with ``_`` (disabled/template convention)
      - anything under a ``legacy/`` directory
      - for dir-per-agent entries, only the YAML matching the dir name
        (e.g. ``mamba/mamba.yaml``) is collected, to avoid duplicates when
        an agent dir holds multiple yamls.
    """
    if agents_dir is not None:
        d = agents_dir.resolve()
    elif USER_AGENTS_DIR.is_dir():
        d = USER_AGENTS_DIR.resolve()
    else:
        d = DEFAULT_AGENTS_DIR.resolve()

    if not d.is_dir():
        return []

    found: list[Path] = []

    # Top-level flat yamls: agents/<name>.yaml
    for p in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
        if p.name.startswith("_"):
            continue
        found.append(p)

    # Dir-per-agent: agents/<name>/<name>.yaml
    for sub in sorted(p for p in d.iterdir() if p.is_dir()):
        if sub.name == "legacy" or sub.name.startswith("_"):
            continue
        for ext in (".yaml", ".yml"):
            candidate = sub / f"{sub.name}{ext}"
            if candidate.exists():
                found.append(candidate)
                break

    return found


def load_cfg(config_path: str | None) -> dict:
    """Load config or exit with error."""
    try:
        return load_config(Path(config_path) if config_path else None)
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


def read_template(name: str) -> str:
    """Read a template file from the package."""
    pkg = "scitex_orochi.templates"
    try:
        ref = importlib.resources.files(pkg).joinpath(name)
        return ref.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        click.echo(f"Error: Cannot find template: {exc}", err=True)
        sys.exit(1)


def launch_via_agent_container(
    agent_config_path: str,
    dry_run: bool,
    as_json: bool,
    force: bool = False,
) -> None:
    """Dispatch an agent launch through scitex-agent-container.

    scitex-agent-container itself is now Orochi-agnostic. This function is
    the bridge: it parses the ``spec.orochi:`` section ourselves, generates
    the MCP config file, augments the yaml's ``claude.flags`` with
    ``--mcp-config`` and ``--dangerously-load-development-channels``, writes
    a shim yaml to ``/tmp``, and then calls ``agent_start`` on the shim.
    After ``agent_start`` returns, the Orochi sidecar thread is started in
    this process so the agent registers with the hub.

    Args:
        agent_config_path: Path to the agent yaml file.
        dry_run: If True, print what would happen without launching.
        as_json: Emit JSON status messages.
        force: If True, stop any existing instance first then relaunch.
    """
    if not HAS_AGENT_CONTAINER:
        click.echo(
            "Error: scitex-agent-container is not installed.\n"
            "  Install with: pip install scitex-orochi[agent-container]",
            err=True,
        )
        sys.exit(1)

    config_path = Path(agent_config_path).resolve()
    if not config_path.exists():
        click.echo(f"Error: Agent config not found: {config_path}", err=True)
        sys.exit(1)

    # Deferred import so the CLI module loads even when the bridge isn't
    # available (e.g., during early CLI smoke tests).
    from scitex_orochi._agent_container_bridge import (
        load_orochi_spec,
        prepare_shim_yaml,
        start_orochi_sidecar,
        write_mcp_config_file,
    )

    orochi_spec = load_orochi_spec(config_path)

    if dry_run:
        result = {
            "action": "launch-via-agent-container",
            "config": str(config_path),
            "force": force,
            "orochi_enabled": orochi_spec.is_enabled,
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo("Would launch agent via scitex-agent-container:")
            click.echo(f"  Config: {config_path}")
            if orochi_spec.is_enabled:
                click.echo(f"  Orochi: hosts={orochi_spec.hosts}")
            if force:
                click.echo("  Mode: --force (stop existing first)")
        return

    # Build a shim yaml with Orochi-specific flags injected, so
    # scitex-agent-container can stay generic. For remote agents, the
    # generated mcp-config json is also scp'd to the remote at the same
    # path so claude finds it there.
    launch_yaml_path = prepare_shim_yaml(
        config_path, orochi_spec, write_mcp_config_file
    )

    try:
        _ac_agent_start(str(launch_yaml_path), force=force)  # type: ignore[possibly-unbound]
        if as_json:
            click.echo(json.dumps({"status": "launched", "config": str(config_path)}))
        else:
            click.echo(f"Agent launched via scitex-agent-container: {config_path}")
    except Exception as exc:
        click.echo(f"Error: Agent container launch failed: {exc}", err=True)
        sys.exit(1)

    # Start the Orochi sidecar in this process so the agent registers
    # with the hub. agent-container no longer does this for us.
    if orochi_spec.is_enabled:
        try:
            import yaml as _yaml

            with open(config_path) as f:
                _raw = _yaml.safe_load(f) or {}
            _spec = _raw.get("spec", {}) or {}
            _meta = _raw.get("metadata", {}) or {}
            start_orochi_sidecar(
                agent_name=_meta.get("name", config_path.stem),
                orochi=orochi_spec,
                agent_env=_spec.get("env", {}) or {},
                agent_labels=_meta.get("labels", {}) or {},
            )
        except Exception as exc:
            click.echo(f"Warning: Orochi sidecar failed to start: {exc}", err=True)


def screen_exists(name: str, ssh_prefix: str | None = None) -> bool:
    """Check if a screen session exists (local or remote)."""
    cmd = "screen -ls 2>/dev/null"
    if ssh_prefix:
        cmd = f"{ssh_prefix} {cmd}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return name in result.stdout


def legacy_launch_master(cfg: dict, dry_run: bool, as_json: bool) -> None:
    """Launch master via legacy orochi-config.yaml."""
    master = cfg["master"]
    screen_name = master["name"]
    model = master.get("model", "opus[1m]")
    channels = master.get("channels", ["#general"])
    server = cfg["server"]

    tvars = build_template_vars(cfg, role="master")
    rendered = render_template(read_template("master-claude.md"), tvars)

    orochi_claude_md = Path(f"/tmp/{screen_name}-CLAUDE.md")
    orochi_claude_md.write_text(rendered, encoding="utf-8")

    channel_args = " ".join(f"--channel server:scitex-orochi:{ch}" for ch in channels)
    launch_cmd = (
        f"screen -dmS {screen_name} bash -c '"
        f"export SCITEX_OROCHI_HOST={server['host']}; "
        f"export SCITEX_OROCHI_PORT={server['ws_port']}; "
        f"export SCITEX_OROCHI_AGENT={screen_name}; "
        f"claude --model {model} "
        f'--system-prompt "$(cat {orochi_claude_md})" '
        f"{channel_args}; "
        f"exec bash'"
    )

    if dry_run:
        result = {
            "action": "launch-master",
            "screen": screen_name,
            "model": model,
            "channels": channels,
            "command": launch_cmd,
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo("Would execute:")
            click.echo(launch_cmd)
            click.echo(f"\nRendered CLAUDE.md at: {orochi_claude_md}")
        return

    if screen_exists(screen_name):
        click.echo(
            f"Error: Screen '{screen_name}' already exists.\n"
            f"  Kill it first: screen -S {screen_name} -X quit",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Launching {screen_name}...")
    subprocess.run(launch_cmd, shell=True, check=True)

    if as_json:
        click.echo(
            json.dumps({"status": "launched", "screen": screen_name, "model": model})
        )
    else:
        click.echo(f"Started screen session: {screen_name}")
        click.echo(f"Attach with: screen -r {screen_name}")


def legacy_launch_head(cfg: dict, name: str, dry_run: bool, as_json: bool) -> None:
    """Launch head agent via legacy orochi-config.yaml."""
    try:
        head = _find_head(cfg, name)
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    screen_name = head["name"]
    ssh_cmd = head["ssh"]
    model = head.get("model", "sonnet")
    channels = head.get("channels", ["#general"])
    workdir = head.get("workdir", "~/proj")
    server = cfg["server"]

    tvars = build_template_vars(cfg, role="head", head_name=name)
    rendered = render_template(read_template("head-claude.md"), tvars)

    channel_args = " ".join(f"--channel server:scitex-orochi:{ch}" for ch in channels)
    remote_script = (
        f"cat > /tmp/{screen_name}-CLAUDE.md << 'CLAUDE_EOF'\n"
        f"{rendered}\n"
        f"CLAUDE_EOF\n"
        f"screen -dmS {screen_name} bash -c '"
        f"cd {workdir}; "
        f"export SCITEX_OROCHI_HOST={server['host']}; "
        f"export SCITEX_OROCHI_PORT={server['ws_port']}; "
        f"export SCITEX_OROCHI_AGENT={screen_name}; "
        f"claude --model {model} "
        f'--system-prompt "$(cat /tmp/{screen_name}-CLAUDE.md)" '
        f"{channel_args}; "
        f"exec bash'"
    )
    full_cmd = f"{ssh_cmd} bash -s << 'SSH_EOF'\n{remote_script}\nSSH_EOF"

    if dry_run:
        result = {
            "action": "launch-head",
            "name": name,
            "screen": screen_name,
            "ssh": ssh_cmd,
            "model": model,
            "channels": channels,
            "command": full_cmd,
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo("Would execute via SSH:")
            click.echo(full_cmd)
        return

    if screen_exists(screen_name, ssh_cmd):
        click.echo(
            f"Error: Screen '{screen_name}' already exists on remote.\n"
            f"  Kill it first: {ssh_cmd} screen -S {screen_name} -X quit",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Launching {screen_name} via {ssh_cmd}...")
    result_proc = subprocess.run(
        full_cmd,
        shell=True,
        capture_output=True,
        text=True,
    )
    if result_proc.returncode != 0:
        click.echo(
            f"Error: SSH command failed (exit {result_proc.returncode})",
            err=True,
        )
        if result_proc.stderr:
            click.echo(result_proc.stderr, err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps({"status": "launched", "screen": screen_name, "ssh": ssh_cmd})
        )
    else:
        click.echo(f"Started remote screen session: {screen_name}")
        click.echo(f"Attach with: {ssh_cmd} -t screen -r {screen_name}")
