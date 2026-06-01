"""Shim-yaml generation and remote MCP-config distribution.

This is the part of the bridge that adapts an Orochi-flavored agent
yaml into something scitex-agent-container can launch as-is. The flow:

  1. Parse ``spec.orochi:`` from the user's yaml.
  2. Generate ``mcp-<name>.json`` locally via ``write_mcp_config_file``.
  3. If the agent is remote, scp the mcp-config json to the same path
     on the remote host so ``claude --mcp-config`` finds it there.
  4. Inject ``--mcp-config`` and ``--dangerously-load-development-channels``
     into ``claude.flags`` (deduped).
  5. Write the augmented yaml to ``/tmp/scitex-orochi-shim-yamls/`` and
     return its path. The caller hands that path to
     ``scitex_agent_container.lifecycle.agent_start``.

scitex-agent-container then receives a yaml that already has all the
Orochi flags it needs and stays completely Orochi-agnostic.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path
from typing import Callable

import yaml
from scitex_config._ecosystem import local_state

from .spec import OrochiSpec

logger = logging.getLogger("scitex-orochi.bridge.dispatch")


def prepare_shim_yaml(
    config_path: Path,
    orochi_spec: OrochiSpec,
    write_mcp_config_file: Callable,
    scp_fn: Callable[[str, str, dict], None] | None = None,
) -> Path:
    """Write a shim yaml with Orochi-specific claude flags injected.

    For remote agents, the generated MCP config file is also scp'd to
    the remote at the same path so claude finds it there.

    ``scp_fn`` is an injection point so tests can supply a real
    hand-rolled fake that records its invocations. Production callers
    omit it and the default resolves to the real
    ``scp_mcp_config_to_remote`` at call time. The default is wired
    inside the function (not as a parameter default) because
    ``scp_mcp_config_to_remote`` is defined later in this module.

    Returns the shim path. If Orochi is not enabled, returns the
    original ``config_path`` unchanged (no shim needed).
    """
    if scp_fn is None:
        scp_fn = scp_mcp_config_to_remote
    if not orochi_spec.is_enabled:
        return config_path

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    spec = raw.setdefault("spec", {}) or {}
    metadata = raw.get("metadata", {}) or {}
    agent_name = metadata.get("name", config_path.stem)

    claude_section = spec.setdefault("claude", {}) or {}
    existing_flags = list(claude_section.get("flags", []) or [])

    mcp_path = write_mcp_config_file(
        agent_name=agent_name,
        orochi=orochi_spec,
        agent_env=spec.get("env", {}) or {},
        agent_labels=metadata.get("labels", {}) or {},
    )

    if mcp_path:
        # If the agent runs on a remote host, the mcp-config file we just
        # wrote on the dispatcher needs to land at the same path on the
        # remote so claude can read it there.
        remote_section = spec.get("remote", {}) or {}
        remote_host = remote_section.get("host", "")
        if remote_host:
            scp_fn(mcp_path, remote_host, remote_section)

        # Inject the MCP flags. ORDER MATTERS: --mcp-config MUST come
        # BEFORE --dangerously-load-development-channels because the
        # channels flag references a server by name ("server:scitex-orochi")
        # and the server is only registered after --mcp-config loads the
        # JSON file that declares it. If the order is reversed, the
        # channel registration silently fails and push notifications
        # never arrive — the MCP tools still work but the real-time
        # channel delivery path is dead.
        mcp_config_flag = f"--mcp-config '{mcp_path}'"
        dev_channels_flag = (
            "--dangerously-load-development-channels server:scitex-orochi"
        )

        # Remove any existing instances to prevent duplicates, then
        # re-insert in the correct order (mcp-config first, then channels).
        existing_flags = [
            f
            for f in existing_flags
            if "--mcp-config" not in f
            and "--dangerously-load-development-channels" not in f
        ]
        existing_flags.append(mcp_config_flag)
        existing_flags.append(dev_channels_flag)

        claude_section["flags"] = existing_flags
        spec["claude"] = claude_section
        raw["spec"] = spec

    shim_dir = local_state.runtime_path("orochi", "shim-yamls")
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim_path = shim_dir / config_path.name
    shim_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return shim_path


def _remote_home_dir(target: str, ssh_opts: list[str]) -> str:
    """Return the remote user's ``$HOME``.

    Raises ``RuntimeError`` if ssh fails, returns non-zero, or no
    path-like line is parsable from stdout. We do NOT swallow failures
    here: the caller uses the result to rewrite path prefixes inside the
    mcp-config file, and a silent "remote home unknown" path leads to
    claude starting on the remote and 404-ing on ``--mcp-config`` with
    an opaque error that's hard to trace back to this step.
    """
    proc = subprocess.run(
        ["ssh", *ssh_opts, target, "echo $HOME"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ssh {target} 'echo $HOME' returned rc={proc.returncode}; "
            f"stderr: {proc.stderr.strip() or '(empty)'}"
        )
    # Remote bashrc may print noise to stdout (scitex-resource-monitor
    # "Dashboard started in background" etc). Our $HOME line is
    # usually the last non-empty line that looks like an absolute path.
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("/"):
            return line
    raise RuntimeError(
        f"ssh {target} 'echo $HOME' returned rc=0 but no path-like line "
        f"in stdout (got {proc.stdout!r})"
    )


def scp_mcp_config_to_remote(
    local_path: str,
    remote_host: str,
    remote_section: dict,
) -> None:
    """Copy a generated mcp-config json to ``remote_host:<same path>``.

    The json's ``args[0]`` holds a path to ``mcp_channel.ts`` that was
    resolved on the DISPATCHER (e.g. ``/home/ywatanabe/...`` on Linux).
    That path is wrong on a macOS remote where ``$HOME=/Users/...``, so
    before transferring we detect the remote's home dir and rewrite any
    occurrences of the dispatcher's home prefix to the remote's.

    Creates the parent directory on the remote first. Raises
    ``RuntimeError`` on any failure (remote home detection, mkdir,
    transfer) — we do NOT silently fall back, because the caller's
    contract is "after this returns, the file is at ``target:local_path``
    with the correct path-prefix rewriting". A partial / wrong-prefix
    file on the remote causes the agent's claude to 404 on
    ``--mcp-config`` later with an opaque error.
    """
    user = remote_section.get("user", "") or "ywatanabe"
    target = f"{user}@{remote_host}"
    remote_dir = str(Path(local_path).parent)

    ssh_opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

    # Rewrite ts_path in the JSON for cross-platform portability.
    # _remote_home_dir() raises if the remote $HOME can't be determined;
    # we let that propagate so the operator sees the real ssh error.
    local_home = str(Path.home())
    remote_home = _remote_home_dir(target, ssh_opts)
    if remote_home != local_home:
        raw = Path(local_path).read_text()
        rewritten = raw.replace(local_home, remote_home)
        rewritten_bytes = rewritten.encode("utf-8")
        logger.info(
            "Rewrote ts_path home prefix %s -> %s for %s",
            local_home,
            remote_home,
            target,
        )
    else:
        rewritten_bytes = Path(local_path).read_bytes()

    # Use ``cat | ssh 'cat >'`` rather than scp/sftp because the OpenSSH
    # scp protocol breaks when the remote login shell prints to stdout
    # during init (a common issue on machines with chatty bashrc setups
    # — e.g. scitex-resource-monitor's "Dashboard started in background"
    # banner on the NAS). The cat-pipe approach is robust against shell
    # init noise because the noise lands on a different file descriptor
    # than the data stream.
    mkdir_proc = subprocess.run(
        ["ssh", *ssh_opts, target, f"mkdir -p {shlex.quote(remote_dir)}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if mkdir_proc.returncode != 0:
        raise RuntimeError(
            f"Remote mkdir {remote_dir} on {target} failed "
            f"(rc={mkdir_proc.returncode}); "
            f"stderr: {mkdir_proc.stderr.strip() or '(empty)'}"
        )

    transfer_proc = subprocess.run(
        [
            "ssh",
            *ssh_opts,
            target,
            f"cat > {shlex.quote(local_path)}",
        ],
        input=rewritten_bytes,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if transfer_proc.returncode != 0:
        raise RuntimeError(
            f"Remote write to {target}:{local_path} failed "
            f"(rc={transfer_proc.returncode}); "
            f"stderr: "
            f"{transfer_proc.stderr.decode('utf-8', 'replace').strip() or '(empty)'}"
        )

    logger.info("Distributed mcp-config to %s:%s", target, local_path)
