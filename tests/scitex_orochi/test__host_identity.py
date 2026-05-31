"""Tests for the host-identity resolver."""

from __future__ import annotations

import socket

import pytest
import yaml

from scitex_orochi import _host_identity as hi


@pytest.fixture(autouse=True)
def _isolate_identity(tmp_path, monkeypatch):
    path = tmp_path / "host-identity.yaml"
    monkeypatch.setattr(hi, "HOST_IDENTITY_PATH", path)
    hi.reset_cache()
    yield path
    hi.reset_cache()


def test_defaults_used_when_file_missing(_isolate_identity):
    aliases = set(hi.load_host_identity()["aliases"])
    assert socket.gethostname() in aliases
    assert "localhost" in aliases


def test_file_aliases_merged_with_defaults(_isolate_identity):
    _isolate_identity.write_text(yaml.safe_dump({"aliases": ["mba", "macbook"]}))
    hi.reset_cache()
    aliases = set(hi.load_host_identity()["aliases"])
    assert {"mba", "macbook", "localhost", socket.gethostname()} <= aliases


def test_is_local_matches_alias(_isolate_identity):
    _isolate_identity.write_text(yaml.safe_dump({"aliases": ["mba"]}))
    hi.reset_cache()
    assert hi.is_local("mba") is True
    assert hi.is_local("localhost") is True
    assert hi.is_local(None) is True
    assert hi.is_local("spartan") is False


def test_invalid_yaml_raises(_isolate_identity):
    _isolate_identity.write_text("aliases: [unterminated")
    hi.reset_cache()
    with pytest.raises(RuntimeError, match="Invalid YAML"):
        hi.load_host_identity()


def test_non_mapping_raises(_isolate_identity):
    _isolate_identity.write_text("- just\n- a\n- list\n")
    hi.reset_cache()
    with pytest.raises(RuntimeError, match="must be a YAML mapping"):
        hi.load_host_identity()


def test_run_on_local_does_not_ssh(_isolate_identity, monkeypatch):
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        return type("CP", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(hi.subprocess, "run", fake_run)
    hi.run_on("localhost", ["echo", "hi"])
    assert captured["argv"] == ["echo", "hi"]


def test_run_on_remote_uses_ssh(_isolate_identity, monkeypatch):
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        return type("CP", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(hi.subprocess, "run", fake_run)
    hi.run_on("spartan", ["echo", "hi"])
    assert captured["argv"][0] == "ssh"
    assert "spartan" in captured["argv"]
    assert captured["argv"][-2:] == ["echo", "hi"]
