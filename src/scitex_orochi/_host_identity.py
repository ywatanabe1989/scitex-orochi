"""Host-identity resolver: decide local vs remote execution by name.

Canonical name + aliases come from :mod:`scitex_resource` —
``~/.scitex/resource/config.yaml`` ``machine.canonical_name`` /
``machine.aliases``. See scitex-resource README and the scitex-python
``arch-local-state-directories`` skill for the ecosystem-wide rule
(one package owns each domain; this module consumes the API).

Legacy ``~/.scitex/host-identity.yaml`` is still read for back-compat;
its aliases are merged into the result. Migrate by moving the contents
into ``~/.scitex/resource/config.yaml`` under ``machine.aliases``.
"""

from __future__ import annotations

import socket
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

# Legacy back-compat path. New deployments should use
# ~/.scitex/resource/config.yaml (owned by scitex-resource).
HOST_IDENTITY_PATH = Path.home() / ".scitex" / "host-identity.yaml"


def _default_aliases() -> set[str]:
    hostname = socket.gethostname()
    return {
        "localhost",
        "",
        hostname,
        hostname.split(".")[0],
        socket.getfqdn(),
    }


def _resource_aliases() -> set[str]:
    """Aliases declared in scitex-resource's machine config."""
    try:
        from scitex_resource import get_machine_config, get_machine_name
    except ImportError:
        return set()
    out: set[str] = set()
    name = (get_machine_name() or "").strip()
    if name:
        out.add(name)
    cfg = get_machine_config()
    for a in cfg.get("aliases") or []:
        if isinstance(a, str) and a:
            out.add(a)
    return out


@lru_cache(maxsize=1)
def load_host_identity() -> dict:
    """Load identity (cached). Aliases merged from scitex-resource +
    legacy ``host-identity.yaml`` + socket-derived defaults.
    """
    aliases: set[str] = set()
    data: dict = {}
    if HOST_IDENTITY_PATH.exists():
        try:
            data = yaml.safe_load(HOST_IDENTITY_PATH.read_text()) or {}
        except yaml.YAMLError as exc:
            raise RuntimeError(f"Invalid YAML in {HOST_IDENTITY_PATH}: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(
                f"{HOST_IDENTITY_PATH} must be a YAML mapping, got {type(data).__name__}"
            )
        aliases |= set(data.get("aliases") or [])

    aliases |= _resource_aliases()
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
