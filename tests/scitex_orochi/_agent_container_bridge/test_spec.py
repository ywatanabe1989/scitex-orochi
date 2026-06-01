"""Tests for ``_agent_container_bridge/spec.py``.

This is the parser for the ``spec.orochi:`` section of an agent yaml.
The bridge surface — the only formal SoC seam between scitex-orochi and
scitex-agent-container — had zero direct tests before this file (the
sibling ``test_connector.py`` is an AST-only structural surface check).

These tests drive the parser through every shape it supports:

- empty / missing section -> default disabled spec
- legacy ``host:`` (singular) vs new ``hosts:`` (plural)
- numeric coercion for the four int fields
- ``is_enabled`` property requires both ``enabled=True`` AND a non-empty
  host list (a subtle invariant — an "enabled but no hosts" spec is a
  no-op, and the property is what the launch path checks).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitex_orochi._agent_container_bridge.spec import (
    OrochiSpec,
    load_orochi_spec,
)


@pytest.fixture
def write_yaml(tmp_path):
    """Return a helper that writes a yaml dict to a tmp file and returns its path."""

    def _write(data: dict) -> Path:
        p = tmp_path / "agent.yaml"
        p.write_text(yaml.safe_dump(data, sort_keys=False))
        return p

    return _write


# ---------------------------------------------------------------------------
# OrochiSpec defaults + is_enabled invariant
# ---------------------------------------------------------------------------


def test_default_spec_is_not_enabled():
    """A bare ``OrochiSpec()`` is the "Orochi off" baseline."""
    s = OrochiSpec()
    assert s.enabled is False
    assert s.hosts == []
    assert s.port == 8559
    assert s.ws_path == "/ws/agent/"
    assert s.token_env == "SCITEX_OROCHI_TOKEN"
    assert s.channels == []
    assert s.heartbeat_interval == 30
    assert s.reconnect_interval == 10
    assert s.reconnect_max_retries == 0
    assert s.ts_path == ""
    assert s.is_enabled is False


def test_is_enabled_requires_both_flag_and_hosts():
    """enabled=True alone is a no-op; hosts alone is a no-op."""
    assert OrochiSpec(enabled=True, hosts=[]).is_enabled is False
    assert OrochiSpec(enabled=False, hosts=["h1"]).is_enabled is False
    assert OrochiSpec(enabled=True, hosts=["h1"]).is_enabled is True


# ---------------------------------------------------------------------------
# load_orochi_spec — section-missing cases
# ---------------------------------------------------------------------------


def test_missing_spec_section_yields_default(write_yaml):
    path = write_yaml({})
    s = load_orochi_spec(path)
    assert s == OrochiSpec()


def test_missing_orochi_section_yields_default(write_yaml):
    path = write_yaml({"spec": {"foo": "bar"}})
    s = load_orochi_spec(path)
    assert s == OrochiSpec()


def test_orochi_section_explicit_null_yields_default(write_yaml):
    """``spec.orochi: ~`` (yaml null) must not crash on ``.get`` calls."""
    path = write_yaml({"spec": {"orochi": None}})
    s = load_orochi_spec(path)
    assert s == OrochiSpec()


# ---------------------------------------------------------------------------
# load_orochi_spec — hosts forms
# ---------------------------------------------------------------------------


def test_hosts_plural_form(write_yaml):
    path = write_yaml(
        {"spec": {"orochi": {"enabled": True, "hosts": ["a.example", "b.example"]}}}
    )
    s = load_orochi_spec(path)
    assert s.enabled is True
    assert s.hosts == ["a.example", "b.example"]
    assert s.is_enabled is True


def test_legacy_host_singular_form_is_promoted_to_list(write_yaml):
    """Backcompat: older yamls used singular ``host:``."""
    path = write_yaml({"spec": {"orochi": {"enabled": True, "host": "legacy.example"}}})
    s = load_orochi_spec(path)
    assert s.hosts == ["legacy.example"]
    assert s.is_enabled is True


def test_hosts_plural_wins_when_both_present(write_yaml):
    """If both ``hosts`` and ``host`` are present, plural wins (newer)."""
    path = write_yaml(
        {
            "spec": {
                "orochi": {
                    "enabled": True,
                    "hosts": ["new1", "new2"],
                    "host": "old",
                }
            }
        }
    )
    s = load_orochi_spec(path)
    assert s.hosts == ["new1", "new2"]


def test_empty_hosts_list_falls_back_to_host_singular(write_yaml):
    """``hosts: []`` is "no plural form" — fall back to ``host:``."""
    path = write_yaml(
        {
            "spec": {
                "orochi": {
                    "enabled": True,
                    "hosts": [],
                    "host": "fallback.example",
                }
            }
        }
    )
    s = load_orochi_spec(path)
    assert s.hosts == ["fallback.example"]


def test_no_hosts_anywhere_keeps_enabled_but_is_enabled_false(write_yaml):
    """``enabled: true`` with no hosts is a soft-disable (invariant test)."""
    path = write_yaml({"spec": {"orochi": {"enabled": True}}})
    s = load_orochi_spec(path)
    assert s.enabled is True
    assert s.hosts == []
    assert s.is_enabled is False


# ---------------------------------------------------------------------------
# load_orochi_spec — numeric coercion + every field
# ---------------------------------------------------------------------------


def test_full_field_set_with_string_numbers_is_coerced(write_yaml):
    """yaml allows int-looking strings; the parser must int() them."""
    path = write_yaml(
        {
            "spec": {
                "orochi": {
                    "enabled": True,
                    "hosts": ["h1"],
                    "port": "9559",
                    "ws_path": "/ws/custom/",
                    "token_env": "CUSTOM_TOKEN",
                    "channels": ["#chan-a", "#chan-b"],
                    "heartbeat_interval": "45",
                    "reconnect_interval": "20",
                    "reconnect_max_retries": "5",
                    "ts_path": "/opt/ts/mcp_channel.ts",
                }
            }
        }
    )
    s = load_orochi_spec(path)
    assert s.port == 9559
    assert s.ws_path == "/ws/custom/"
    assert s.token_env == "CUSTOM_TOKEN"
    assert s.channels == ["#chan-a", "#chan-b"]
    assert s.heartbeat_interval == 45
    assert s.reconnect_interval == 20
    assert s.reconnect_max_retries == 5
    assert s.ts_path == "/opt/ts/mcp_channel.ts"
    assert s.is_enabled is True


def test_channels_null_yields_empty_list(write_yaml):
    """``channels: ~`` must not propagate None to ``.channels`` (downstream
    callers do ``orochi.channels or [...]`` patterns)."""
    path = write_yaml(
        {"spec": {"orochi": {"enabled": True, "hosts": ["h"], "channels": None}}}
    )
    s = load_orochi_spec(path)
    assert s.channels == []


def test_load_accepts_str_path(write_yaml):
    """Smoke: ``load_orochi_spec`` accepts both Path and str."""
    path = write_yaml({"spec": {"orochi": {"enabled": True, "hosts": ["h"]}}})
    s = load_orochi_spec(str(path))
    assert s.is_enabled is True
