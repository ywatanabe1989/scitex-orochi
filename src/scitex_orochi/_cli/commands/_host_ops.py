"""Shared helpers for the host-side ops subcommands.

Provides the common building blocks that the shell scripts duplicated:

* ``parse_head_machines`` / ``parse_all_machines`` -- read
  ``orochi-machines.yaml`` with PyYAML (falling back to a tiny regex
  parser so the CLI still runs in a sparse interpreter).
* ``resolve_self_host`` -- canonical fleet label for *this* box
  (``SCITEX_OROCHI_HOSTNAME`` env > ``scripts/client/resolve-orochi_hostname``
  script > ``socket.gethostname()`` short form).
* ``state_log_dirs`` -- OS-aware pair of (state_dir, log_dir) paths.
* ``load_workspace_token`` -- env first, optional dotfiles secret file
  fallback (same path every shell script already sources).
"""

from __future__ import annotations

import os
import platform
import re
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _repo_root_candidate() -> Path:
    """Best-effort repo root for locating ``orochi-machines.yaml`` when the
    CLI is invoked from outside the checkout.

    Precedence:
      1. ``$SCITEX_OROCHI_REPO_ROOT`` env (installer injects this)
      2. Walk up from CWD looking for ``orochi-machines.yaml``
      3. ``~/proj/scitex-orochi`` (developer convention)
      4. CWD as last resort
    """
    env = os.environ.get("SCITEX_OROCHI_REPO_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    here = Path.cwd().resolve()
    for p in [here, *here.parents]:
        if (p / "orochi-machines.yaml").is_file():
            return p
    fallback = Path.home() / "proj" / "scitex-orochi"
    if (fallback / "orochi-machines.yaml").is_file():
        return fallback
    return here


def default_machines_yaml() -> Path:
    env = os.environ.get("MACHINES_YAML")
    if env:
        return Path(env)
    return _repo_root_candidate() / "orochi-machines.yaml"


# ---------------------------------------------------------------------------
# machines.yaml parsing
# ---------------------------------------------------------------------------

@dataclass
class MachineEntry:
    canonical_name: str
    role: str = ""
    orochi_hostname: str = ""
    aliases: tuple[str, ...] = ()
    expected_tmux_sessions: tuple[str, ...] = ()


def _regex_fallback_parse(text: str) -> list[MachineEntry]:
    """Minimal fallback parser for environments without PyYAML."""
    out: list[MachineEntry] = []
    blocks = re.split(r"^\s*-\s+canonical_name:\s*", text, flags=re.MULTILINE)

    def _collect_list(blk: str, key: str) -> list[str]:
        m = re.search(
            rf"^\s*{key}:\s*\n((?:\s+-\s+[^\n]+\n)+)",
            blk,
            flags=re.MULTILINE,
        )
        acc: list[str] = []
        if m:
            for ln in m.group(1).splitlines():
                m2 = re.match(r"\s*-\s+([A-Za-z0-9_.-]+)", ln)
                if m2:
                    acc.append(m2.group(1).strip())
        return acc

    def _collect_scalar(blk: str, key: str) -> str:
        m = re.search(
            rf"^\s*{key}:\s*([A-Za-z0-9_.-]+)",
            blk,
            flags=re.MULTILINE,
        )
        return m.group(1).strip() if m else ""

    for blk in blocks[1:]:
        mname = re.match(r"([A-Za-z0-9_.-]+)", blk)
        if not mname:
            continue
        name = mname.group(1).strip()
        sessions = _collect_list(blk, "expected_tmux_sessions")
        aliases = _collect_list(blk, "aliases")
        orochi_hostname = _collect_scalar(blk, "orochi_hostname")
        # fleet_role is nested so the scalar helper matches "role: head" too.
        role = ""
        m = re.search(r"role:\s*([A-Za-z0-9_.-]+)", blk)
        if m:
            role = m.group(1).strip()
        if orochi_hostname and orochi_hostname not in aliases:
            aliases.append(orochi_hostname)
        out.append(
            MachineEntry(
                canonical_name=name,
                role=role,
                hostname=hostname,
                aliases=tuple(aliases),
                expected_tmux_sessions=tuple(sessions),
            )
        )
    return out


def parse_all_machines(path: Path | None = None) -> list[MachineEntry]:
    """Return every ``machines[]`` entry from ``orochi-machines.yaml``.

    Silently returns ``[]`` when the file is missing. This keeps the CLI's
    ``--help`` / smoke-test paths orochi_alive on a box with no checkout mounted.
    """
    p = path or default_machines_yaml()
    if not p.is_file():
        return []
    try:
        import yaml  # type: ignore[import-not-found]

        doc = yaml.safe_load(p.read_text()) or {}
    except ImportError:
        return _regex_fallback_parse(p.read_text())
    except Exception:
        return _regex_fallback_parse(p.read_text())

    out: list[MachineEntry] = []
    for m in doc.get("machines") or []:
        if not isinstance(m, dict):
            continue
        name = (m.get("canonical_name") or "").strip()
        if not name:
            continue
        fleet_role = m.get("fleet_role") or {}
        role = ""
        if isinstance(fleet_role, dict):
            role = (fleet_role.get("role") or "").strip()
        aliases_raw = m.get("aliases") or []
        aliases = [str(a) for a in aliases_raw if a]
        orochi_hostname = (m.get("orochi_hostname") or "").strip()
        if orochi_hostname and orochi_hostname not in aliases:
            aliases.append(orochi_hostname)
        sessions = [
            str(s) for s in (m.get("expected_tmux_sessions") or []) if s
        ]
        out.append(
            MachineEntry(
                canonical_name=name,
                role=role,
                hostname=hostname,
                aliases=tuple(aliases),
                expected_tmux_sessions=tuple(sessions),
            )
        )
    return out


def parse_head_machines(path: Path | None = None) -> list[MachineEntry]:
    """Just the head-role machines, in yaml order."""
    return [m for m in parse_all_machines(path) if m.role == "head"]


# ---------------------------------------------------------------------------
# Self identity
# ---------------------------------------------------------------------------

def resolve_self_host() -> str:
    """Canonical fleet label for *this* box.

    Order matches the shell scripts:
      1. ``$SCITEX_OROCHI_HOSTNAME`` env (healer/init seeds this)
      2. ``scripts/client/resolve-orochi_hostname`` helper (repo-local)
      3. ``socket.gethostname()`` short form
    """
    env = os.environ.get("SCITEX_OROCHI_HOSTNAME")
    if env:
        return env.strip()
    helper = _repo_root_candidate() / "scripts" / "client" / "resolve-orochi_hostname"
    if helper.is_file() and os.access(helper, os.X_OK):
        try:
            out = subprocess.run(
                [str(helper)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    return socket.gethostname().split(".")[0]


# ---------------------------------------------------------------------------
# OS-aware state/log dirs
# ---------------------------------------------------------------------------

def state_log_dirs(
    state_env: str | None = None,
    log_env: str | None = None,
    sub: str = "scitex",
) -> tuple[Path, Path]:
    """Return a ``(state_dir, log_dir)`` pair.

    Honours the same env-var precedence the shell scripts use:
    ``<FOO>_STATE_DIR``, ``<FOO>_LOG_DIR`` with macOS defaulting log
    output to ``~/Library/Logs/scitex`` and Linux to
    ``~/.local/state/scitex``.
    """
    state_env_val = os.environ.get(state_env) if state_env else None
    state_dir = Path(state_env_val) if state_env_val else (
        Path.home() / ".local" / "state" / sub
    )
    if platform.system() == "Darwin":
        log_default = Path.home() / "Library" / "Logs" / sub
    else:
        log_default = Path.home() / ".local" / "state" / sub
    log_env_val = os.environ.get(log_env) if log_env else None
    log_dir = Path(log_env_val) if log_env_val else log_default
    return state_dir, log_dir


# ---------------------------------------------------------------------------
# Workspace token
# ---------------------------------------------------------------------------

def load_workspace_token() -> str | None:
    """Return the Orochi workspace token, or None if we can't find one.

    Checks ``$SCITEX_OROCHI_TOKEN`` first; if unset, grep the dotfiles
    secrets file for ``SCITEX_OROCHI_TOKEN=...`` (same path the shell
    scripts source).
    """
    env = os.environ.get("SCITEX_OROCHI_TOKEN")
    if env:
        return env
    src = Path.home() / ".dotfiles/src/.bash.d/secrets/010_scitex/01_orochi.src"
    if src.is_file():
        try:
            for line in src.read_text().splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip().lstrip("export ").strip()
                if key == "SCITEX_OROCHI_TOKEN":
                    # Strip leading/trailing quotes if any.
                    return val.strip().strip("\"'")
        except OSError:
            pass
    return None


__all__ = [
    "MachineEntry",
    "default_machines_yaml",
    "load_workspace_token",
    "parse_all_machines",
    "parse_head_machines",
    "resolve_self_host",
    "state_log_dirs",
]
