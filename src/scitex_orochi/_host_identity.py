"""Host-identity resolver: decide local vs remote execution by name.

Each machine declares the names that mean "me" in
``~/.scitex/orochi/host-identity.yaml``. Code that decides whether to run
a command locally or via SSH consults :func:`is_local`.

Example file::

    # ~/.scitex/orochi/host-identity.yaml
    aliases:
      - mba
      - Yusukes-MacBook-Air
      - localhost

If the file is absent, sensible defaults are derived from ``socket``:
``hostname``, short hostname, FQDN, and the literals ``localhost`` / ``""``.
That keeps fresh installs working; an explicit file is recommended once
the machine acquires SSH aliases that differ from its real hostname.
"""

from __future__ import annotations

import socket
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

HOST_IDENTITY_PATH = Path.home() / ".scitex" / "orochi" / "host-identity.yaml"


def _default_aliases() -> set[str]:
    hostname = socket.gethostname()
    return {
        "localhost",
        "",
        hostname,
        hostname.split(".")[0],
        socket.getfqdn(),
    }


@lru_cache(maxsize=1)
def load_host_identity() -> dict:
    """Load identity file (cached). Returns dict with at least ``aliases``."""
    if HOST_IDENTITY_PATH.exists():
        try:
            data = yaml.safe_load(HOST_IDENTITY_PATH.read_text()) or {}
        except yaml.YAMLError as exc:
            raise RuntimeError(f"Invalid YAML in {HOST_IDENTITY_PATH}: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(
                f"{HOST_IDENTITY_PATH} must be a YAML mapping, got {type(data).__name__}"
            )
        aliases = set(data.get("aliases") or [])
    else:
        data = {}
        aliases = set()

    aliases |= _default_aliases()
    data["aliases"] = sorted(a for a in aliases if a is not None)
    return data


def is_local(host: str | None) -> bool:
    """Return True if ``host`` refers to this machine."""
    if host is None:
        return True
    return host in set(load_host_identity()["aliases"])


def run_on(
    host: str | None,
    cmd: list[str],
    *,
    check: bool = False,
    capture_output: bool = False,
    text: bool = True,
    timeout: float | None = None,
    ssh_options: Iterable[str] | None = None,
) -> subprocess.CompletedProcess:
    """Execute ``cmd`` locally if ``host`` is local, else via SSH.

    SSH uses ``BatchMode=yes`` by default so it fails fast on missing keys
    instead of hanging on a password prompt. Override with ``ssh_options``.
    """
    if is_local(host):
        argv = cmd
    else:
        opts = (
            list(ssh_options)
            if ssh_options is not None
            else [
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
            ]
        )
        argv = ["ssh", *opts, host, *cmd]
    return subprocess.run(
        argv,
        check=check,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
    )


def reset_cache() -> None:
    """Clear the cached identity (for tests / after editing the file)."""
    load_host_identity.cache_clear()
