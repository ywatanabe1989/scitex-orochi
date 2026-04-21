"""Regression tests for ``agent_meta_pkg._machine.resolve_machine_label``.

Root cause of lead msg#15578 (proj-neurovista displayed as mba while
actually running on spartan) was client-side env-first prioritisation:
``resolve_machine_label()`` previously honoured
``$SCITEX_OROCHI_HOSTNAME`` over the live ``socket.gethostname()``
call, so a stale env var inherited into a spartan process silently
misreported the host.

The fix flips the priority order: live ``hostname()`` first
(potentially mapped through ``config.yaml`` aliases), env vars only
when the kernel returns an empty hostname. These tests guard against
regression of that priority flip.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

# Import the client-side resolver by path since scripts/client isn't a
# package on the default Python path.
import importlib.util

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "client"
    / "agent_meta_pkg"
    / "_machine.py"
)
_spec = importlib.util.spec_from_file_location("_machine_under_test", _MODULE_PATH)
_machine = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader, f"cannot load {_MODULE_PATH}"
_spec.loader.exec_module(_machine)  # type: ignore[attr-defined]
resolve_machine_label = _machine.resolve_machine_label


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Each test starts with a clean env slate so env-leakage from the
    test runner can't skew the result."""
    monkeypatch.delenv("SCITEX_OROCHI_HOSTNAME", raising=False)
    monkeypatch.delenv("SCITEX_OROCHI_MACHINE", raising=False)
    yield


def test_returns_live_hostname_when_env_unset(monkeypatch):
    """With no env overrides, the resolver returns whatever
    ``socket.gethostname()`` says (trimmed to the short form)."""
    monkeypatch.setattr(socket, "gethostname", lambda: "spartan-login1")
    # Force the config.yaml lookup to miss so we exercise the raw-host
    # fallback path directly.
    monkeypatch.setattr(_machine, "Path", _NoConfigPath)
    assert resolve_machine_label() == "spartan-login1"


def test_env_var_ignored_when_hostname_populated(monkeypatch):
    """This is the direct regression test for lead msg#15578. A stale
    ``SCITEX_OROCHI_HOSTNAME=mba`` env var — inherited from a shared
    tmux / systemd env that originally ran on mba — must NOT override
    the live hostname when the kernel knows who it is."""
    monkeypatch.setenv("SCITEX_OROCHI_HOSTNAME", "mba")
    monkeypatch.setattr(socket, "gethostname", lambda: "spartan-login1")
    monkeypatch.setattr(_machine, "Path", _NoConfigPath)
    # Despite the misleading env, the resolver trusts the kernel.
    assert resolve_machine_label() == "spartan-login1"


def test_env_var_used_when_hostname_empty(monkeypatch):
    """When ``gethostname()`` returns an empty string (stripped
    container / some odd WSL states), the env override is the only
    identity signal available and IS honoured as a last-resort."""
    monkeypatch.setenv("SCITEX_OROCHI_HOSTNAME", "mba")
    monkeypatch.setattr(socket, "gethostname", lambda: "")
    monkeypatch.setattr(_machine, "Path", _NoConfigPath)
    assert resolve_machine_label() == "mba"


def test_short_name_stripped_from_fqdn(monkeypatch):
    """A FQDN like ``spartan-login1.hpc.unimelb.edu.au`` is reduced
    to the short name ``spartan-login1`` — the canonical fleet label
    is always the first dot-separated segment."""
    monkeypatch.setattr(
        socket, "gethostname", lambda: "spartan-login1.hpc.unimelb.edu.au"
    )
    monkeypatch.setattr(_machine, "Path", _NoConfigPath)
    assert resolve_machine_label() == "spartan-login1"


class _NoConfigPath:
    """Minimal ``pathlib.Path`` stand-in that makes the config.yaml
    lookup in ``resolve_machine_label`` miss, so tests exercise the
    plain ``gethostname()`` return path without touching a real
    filesystem."""

    def __init__(self, *parts):
        pass

    @staticmethod
    def home():
        return _NoConfigPath()

    def __truediv__(self, other):
        return _NoConfigPath()

    def exists(self):
        return False

    def read_text(self):  # pragma: no cover — exists() returns False
        raise AssertionError("should not be called when exists() is False")
