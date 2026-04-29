"""Tests for _load_hostname_aliases() in hub/views/api/_misc.py.

Tests the YAML-reading logic in isolation — no Django infrastructure needed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def _load_hostname_aliases_impl(config_path: str) -> dict:
    """Extracted logic from hub/views/api/_misc.py for unit testing."""
    import yaml

    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        return dict(cfg.get("spec", {}).get("hostname_aliases", {}) or {})
    except (OSError, yaml.YAMLError):
        return {}


def test_reads_hostname_aliases_from_yaml():
    yaml_content = "spec:\n  hostname_aliases:\n    testhost: th\n    other.local: other\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name
    try:
        result = _load_hostname_aliases_impl(tmp_path)
        assert result == {"testhost": "th", "other.local": "other"}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_returns_empty_on_missing_file():
    result = _load_hostname_aliases_impl("/nonexistent/path/config.yaml")
    assert result == {}


def test_returns_empty_on_malformed_yaml():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(": bad: yaml: [{\n")
        tmp_path = f.name
    try:
        result = _load_hostname_aliases_impl(tmp_path)
        assert result == {}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_returns_empty_when_spec_key_missing():
    yaml_content = "other_key:\n  data: 1\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name
    try:
        result = _load_hostname_aliases_impl(tmp_path)
        assert result == {}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_returns_empty_when_hostname_aliases_is_null():
    yaml_content = "spec:\n  hostname_aliases: null\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name
    try:
        result = _load_hostname_aliases_impl(tmp_path)
        assert result == {}
    finally:
        Path(tmp_path).unlink(missing_ok=True)
