"""Regression tests for ``agent_meta_pkg._machine.resolve_machine_label``.

Two incidents shape these tests:

1. Lead msg#15578 — proj-neurovista displayed as mba while actually
   running on spartan. Root cause: env-first prioritisation. The fix
   (PR#309) made live ``socket.gethostname()`` win over env vars.

2. ywatanabe msg#16102 — mba host displayed as the raw
   ``Yusukes-MacBook-Air`` on the Agents dashboard. Root cause: PR#309
   skipped the ``hostname_aliases`` map in
   ``~/.scitex/orochi/shared/config.yaml`` that used to translate
   ``Yusukes-MacBook-Air`` → ``mba``. The follow-up fix restores alias
   application before the raw-hostname fallback.

Final resolution order (first non-empty wins):
  1. ``hostname_aliases[gethostname()]`` from shared/config.yaml.
  2. Raw ``gethostname()`` (short form).
  3. Env fallback (``SCITEX_OROCHI_HOSTNAME`` /
     ``SCITEX_OROCHI_MACHINE`` / ``SCITEX_AGENT_CONTAINER_HOSTNAME``) —
     only honoured when ``gethostname()`` is empty.

These tests guard against regression of that ordering.
"""

from __future__ import annotations

# Import the client-side resolver by path since scripts/client isn't a
# package on the default Python path.
import importlib.util
import socket
from pathlib import Path

import pytest

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
    monkeypatch.delenv("SCITEX_AGENT_CONTAINER_HOSTNAME", raising=False)
    yield


def _stub_aliases(monkeypatch, aliases: dict[str, str] | None) -> None:
    """Monkeypatch the alias loader so tests don't touch the real
    shared/config.yaml. Passing ``None`` simulates a missing file."""
    monkeypatch.setattr(
        _machine, "_load_hostname_aliases", lambda: aliases or {}
    )


def test_returns_live_hostname_when_env_unset(monkeypatch):
    """With no env overrides and no alias entry, the resolver returns
    whatever ``socket.gethostname()`` says (trimmed to the short
    form)."""
    monkeypatch.setattr(socket, "gethostname", lambda: "spartan-login1")
    _stub_aliases(monkeypatch, {})
    assert resolve_machine_label() == "spartan-login1"


def test_env_var_ignored_when_hostname_populated(monkeypatch):
    """Direct regression test for lead msg#15578. A stale
    ``SCITEX_OROCHI_HOSTNAME=mba`` env var — inherited from a shared
    tmux / systemd env that originally ran on mba — must NOT override
    the live hostname when the kernel knows who it is."""
    monkeypatch.setenv("SCITEX_OROCHI_HOSTNAME", "mba")
    monkeypatch.setattr(socket, "gethostname", lambda: "spartan-login1")
    _stub_aliases(monkeypatch, {})
    # Despite the misleading env, the resolver trusts the kernel.
    assert resolve_machine_label() == "spartan-login1"


def test_env_var_used_when_hostname_empty(monkeypatch):
    """When ``gethostname()`` returns an empty string (stripped
    container / some odd WSL states), the env override is the only
    identity signal available and IS honoured as a last-resort."""
    monkeypatch.setenv("SCITEX_OROCHI_HOSTNAME", "mba")
    monkeypatch.setattr(socket, "gethostname", lambda: "")
    _stub_aliases(monkeypatch, {})
    assert resolve_machine_label() == "mba"


def test_short_name_stripped_from_fqdn(monkeypatch):
    """A FQDN like ``spartan-login1.hpc.unimelb.edu.au`` is reduced
    to the short name ``spartan-login1`` — the canonical fleet label
    is always the first dot-separated segment."""
    monkeypatch.setattr(
        socket, "gethostname", lambda: "spartan-login1.hpc.unimelb.edu.au"
    )
    _stub_aliases(monkeypatch, {})
    assert resolve_machine_label() == "spartan-login1"


def test_alias_map_translates_raw_hostname(monkeypatch):
    """Direct regression test for ywatanabe msg#16102. Given the live
    hostname ``Yusukes-MacBook-Air`` and an alias map entry mapping
    it to ``mba``, the resolver returns ``mba`` — NOT the raw
    macOS hostname. Without this, the hub dashboard displays
    ``Yusukes-MacBook-Air`` as the mba host's @host label."""
    monkeypatch.setattr(socket, "gethostname", lambda: "Yusukes-MacBook-Air")
    _stub_aliases(monkeypatch, {"Yusukes-MacBook-Air": "mba"})
    assert resolve_machine_label() == "mba"


def test_alias_map_wins_over_env_var(monkeypatch):
    """Aliases are the declarative truth for canonical fleet names.
    Even if an env var is set, when the live hostname has an alias
    entry the alias wins — an env var cannot override the alias
    map, only supplement it when the live hostname is empty."""
    monkeypatch.setenv("SCITEX_OROCHI_HOSTNAME", "totally-wrong")
    monkeypatch.setattr(socket, "gethostname", lambda: "Yusukes-MacBook-Air")
    _stub_aliases(monkeypatch, {"Yusukes-MacBook-Air": "mba"})
    assert resolve_machine_label() == "mba"


def test_raw_hostname_returned_when_no_alias_and_no_env(monkeypatch):
    """Hosts whose raw short hostname already matches the fleet label
    (e.g. ``ywata-note-win``) have no alias entry and no env override,
    yet the resolver must still return the live name verbatim."""
    monkeypatch.setattr(socket, "gethostname", lambda: "ywata-note-win")
    _stub_aliases(monkeypatch, {"Yusukes-MacBook-Air": "mba"})
    assert resolve_machine_label() == "ywata-note-win"


def test_env_fallback_covers_all_three_vars(monkeypatch):
    """When ``gethostname()`` is empty, any of the three documented
    env vars is honoured (matches the TS client's behaviour):
    ``SCITEX_OROCHI_HOSTNAME`` first, then
    ``SCITEX_OROCHI_MACHINE``, then
    ``SCITEX_AGENT_CONTAINER_HOSTNAME``."""
    monkeypatch.setattr(socket, "gethostname", lambda: "")
    _stub_aliases(monkeypatch, {})
    monkeypatch.setenv("SCITEX_AGENT_CONTAINER_HOSTNAME", "container-host")
    assert resolve_machine_label() == "container-host"
    # Higher-priority env wins.
    monkeypatch.setenv("SCITEX_OROCHI_MACHINE", "machine-env")
    assert resolve_machine_label() == "machine-env"
    monkeypatch.setenv("SCITEX_OROCHI_HOSTNAME", "hostname-env")
    assert resolve_machine_label() == "hostname-env"
