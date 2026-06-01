"""Tests for ``_agent_container_bridge/spec.py``.

The bridge surface — the only formal SoC seam between scitex-orochi and
scitex-agent-container — had zero direct tests before this file (the
sibling ``test_connector.py`` is an AST-only structural surface check).

Compliant with scitex-dev linter:
- STX-NM001/2/3: no mock/monkeypatch/patch/Mock anywhere.
- STX-TQ002: every test carries Arrange/Act/Assert markers.
- STX-TQ007: every test asserts exactly one claim (tuple comparison
  where the contract bundles fields; otherwise split into siblings).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scitex_orochi._agent_container_bridge.spec import (
    OrochiSpec,
    load_orochi_spec,
)

# ---------------------------------------------------------------------------
# Tiny helper — write a yaml dict to a tmp file, return its path.
# (Not a fixture so each test states its inputs explicitly.)
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "agent.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


# ---------------------------------------------------------------------------
# OrochiSpec defaults + is_enabled invariant
# ---------------------------------------------------------------------------


def test_default_spec_matches_documented_defaults():
    """``OrochiSpec()`` baseline — every field is the documented default."""
    # Arrange
    expected = (
        False,
        [],
        8559,
        "/ws/agent/",
        "SCITEX_OROCHI_TOKEN",
        [],
        30,
        10,
        0,
        "",
        False,
    )
    # Act
    s = OrochiSpec()
    actual = (
        s.enabled,
        s.hosts,
        s.port,
        s.ws_path,
        s.token_env,
        s.channels,
        s.heartbeat_interval,
        s.reconnect_interval,
        s.reconnect_max_retries,
        s.ts_path,
        s.is_enabled,
    )
    # Assert
    assert actual == expected


def test_is_enabled_requires_both_flag_and_hosts():
    """``is_enabled`` is True iff ``enabled`` AND a non-empty host list."""
    # Arrange
    enabled_no_hosts = OrochiSpec(enabled=True, hosts=[])
    disabled_with_hosts = OrochiSpec(enabled=False, hosts=["h1"])
    enabled_with_hosts = OrochiSpec(enabled=True, hosts=["h1"])
    # Act
    flags = (
        enabled_no_hosts.is_enabled,
        disabled_with_hosts.is_enabled,
        enabled_with_hosts.is_enabled,
    )
    # Assert
    assert flags == (False, False, True)


# ---------------------------------------------------------------------------
# load_orochi_spec — section-missing cases
# ---------------------------------------------------------------------------


def test_missing_spec_section_yields_default(tmp_path):
    """A yaml with no top-level ``spec:`` parses to the default OrochiSpec."""
    # Arrange
    path = _write_yaml(tmp_path, {})
    # Act
    s = load_orochi_spec(path)
    # Assert
    assert s == OrochiSpec()


def test_missing_orochi_section_yields_default(tmp_path):
    """A yaml with ``spec:`` but no ``spec.orochi:`` parses to default."""
    # Arrange
    path = _write_yaml(tmp_path, {"spec": {"foo": "bar"}})
    # Act
    s = load_orochi_spec(path)
    # Assert
    assert s == OrochiSpec()


def test_explicit_null_orochi_section_does_not_crash_on_get(tmp_path):
    """``spec.orochi: ~`` (yaml null) must not crash the parser."""
    # Arrange
    path = _write_yaml(tmp_path, {"spec": {"orochi": None}})
    # Act
    s = load_orochi_spec(path)
    # Assert
    assert s == OrochiSpec()


# ---------------------------------------------------------------------------
# load_orochi_spec — hosts forms
# ---------------------------------------------------------------------------


def test_hosts_plural_form_is_parsed_as_list(tmp_path):
    """``hosts: [a, b]`` becomes ``OrochiSpec.hosts == [a, b]``."""
    # Arrange
    path = _write_yaml(
        tmp_path,
        {"spec": {"orochi": {"enabled": True, "hosts": ["a.example", "b.example"]}}},
    )
    # Act
    s = load_orochi_spec(path)
    # Assert
    assert s.hosts == ["a.example", "b.example"]


def test_legacy_host_singular_form_is_promoted_to_list(tmp_path):
    """Backcompat: older yamls used singular ``host:``."""
    # Arrange
    path = _write_yaml(
        tmp_path,
        {"spec": {"orochi": {"enabled": True, "host": "legacy.example"}}},
    )
    # Act
    s = load_orochi_spec(path)
    # Assert
    assert s.hosts == ["legacy.example"]


def test_hosts_plural_wins_when_both_present(tmp_path):
    """If both ``hosts:`` and ``host:`` are present, plural wins."""
    # Arrange
    path = _write_yaml(
        tmp_path,
        {
            "spec": {
                "orochi": {
                    "enabled": True,
                    "hosts": ["new1", "new2"],
                    "host": "old",
                }
            }
        },
    )
    # Act
    s = load_orochi_spec(path)
    # Assert
    assert s.hosts == ["new1", "new2"]


def test_empty_hosts_list_falls_back_to_singular_host(tmp_path):
    """``hosts: []`` is "no plural form" — fall back to ``host:``."""
    # Arrange
    path = _write_yaml(
        tmp_path,
        {
            "spec": {
                "orochi": {
                    "enabled": True,
                    "hosts": [],
                    "host": "fallback.example",
                }
            }
        },
    )
    # Act
    s = load_orochi_spec(path)
    # Assert
    assert s.hosts == ["fallback.example"]


def test_enabled_true_with_no_hosts_is_a_soft_disable(tmp_path):
    """``enabled: true`` with no hosts -> is_enabled stays False."""
    # Arrange
    path = _write_yaml(tmp_path, {"spec": {"orochi": {"enabled": True}}})
    # Act
    s = load_orochi_spec(path)
    # Assert
    assert (s.enabled, s.hosts, s.is_enabled) == (True, [], False)


# ---------------------------------------------------------------------------
# load_orochi_spec — numeric coercion + every field
# ---------------------------------------------------------------------------


def test_full_yaml_roundtrips_every_field_with_numeric_coercion(tmp_path):
    """yaml allows int-looking strings; the parser must int() them."""
    # Arrange
    path = _write_yaml(
        tmp_path,
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
        },
    )
    expected = OrochiSpec(
        enabled=True,
        hosts=["h1"],
        port=9559,
        ws_path="/ws/custom/",
        token_env="CUSTOM_TOKEN",
        channels=["#chan-a", "#chan-b"],
        heartbeat_interval=45,
        reconnect_interval=20,
        reconnect_max_retries=5,
        ts_path="/opt/ts/mcp_channel.ts",
    )
    # Act
    s = load_orochi_spec(path)
    # Assert
    assert s == expected


def test_channels_null_yields_empty_list(tmp_path):
    """``channels: ~`` must not propagate None to ``.channels``."""
    # Arrange
    path = _write_yaml(
        tmp_path,
        {"spec": {"orochi": {"enabled": True, "hosts": ["h"], "channels": None}}},
    )
    # Act
    s = load_orochi_spec(path)
    # Assert
    assert s.channels == []


def test_load_accepts_str_path(tmp_path):
    """Smoke: ``load_orochi_spec`` accepts both Path and str."""
    # Arrange
    path = _write_yaml(
        tmp_path, {"spec": {"orochi": {"enabled": True, "hosts": ["h"]}}}
    )
    # Act
    s = load_orochi_spec(str(path))
    # Assert
    assert s.is_enabled is True
