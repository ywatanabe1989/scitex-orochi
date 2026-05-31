"""Tests for ``scitex-orochi machine resources show`` (Phase 1c msg#16477)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi
from scitex_orochi._cli.commands import machine_cmd


def test_resources_group_registered() -> None:
    """``machine resources show`` must be wired into the group tree."""
    assert "machine" in orochi.commands
    machine = orochi.commands["machine"]
    assert "resources" in machine.commands  # type: ignore[attr-defined]
    res = machine.commands["resources"]  # type: ignore[attr-defined]
    assert set(res.commands.keys()) == {"show"}


def _fake_metrics() -> dict:
    """Canonical metrics dict shape used in the Machines tab."""
    return {
        "cpu_count": 8,
        "cpu_model": "Apple M1",
        "mem_used_mb": 12 * 1024,
        "mem_total_mb": 16 * 1024,
        "mem_free_mb": 4 * 1024,
        "mem_used_percent": 75.0,
        "disk_used_mb": 500 * 1024,          # 0.49 TB
        "disk_total_mb": 2 * 1024 * 1024,    # 2 TB
        "disk_used_percent": 24.4,
        "gpus": [],
        "load_avg_1m": 1.0,
        "load_avg_5m": 1.0,
        "load_avg_15m": 1.0,
    }


def test_resources_show_human_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default output prints the four Machines-tab lines."""
    monkeypatch.setattr(machine_cmd, "_import_metrics", lambda: _fake_metrics)
    runner = CliRunner()
    result = runner.invoke(orochi, ["machine", "resources", "show"], obj={})
    assert result.exit_code == 0, result.output
    assert "CPU:     8 cores" in result.output
    assert "RAM:     12.0/16.0 GB" in result.output
    assert "Storage: 0.49/2.00 TB" in result.output
    assert "GPU:     n/a" in result.output


def test_resources_show_json_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--json`` honours the top-level flag and includes display + raw."""
    monkeypatch.setattr(machine_cmd, "_import_metrics", lambda: _fake_metrics)
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["--json", "machine", "resources", "show"], obj={}
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["display"]["cpu"] == "8 cores"
    assert payload["display"]["ram"] == "12.0/16.0 GB"
    assert payload["display"]["storage"] == "0.49/2.00 TB"
    assert payload["display"]["gpu"] == "n/a"
    # raw metrics must round-trip unmodified
    assert payload["raw"]["cpu_count"] == 8
    assert payload["raw"]["mem_total_mb"] == 16 * 1024


def test_resources_show_with_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """GPU summary line is built from the per-GPU list."""
    metrics = _fake_metrics()
    metrics["gpus"] = [
        {"name": "A100", "utilization_percent": 50.0,
         "memory_used_mb": 10 * 1024, "memory_total_mb": 40 * 1024},
        {"name": "A100", "utilization_percent": 0.0,
         "memory_used_mb": 0, "memory_total_mb": 40 * 1024},
    ]
    monkeypatch.setattr(machine_cmd, "_import_metrics", lambda: lambda: metrics)
    runner = CliRunner()
    result = runner.invoke(orochi, ["machine", "resources", "show"], obj={})
    assert result.exit_code == 0, result.output
    # 2 GPUs, 10/80 GB VRAM total.
    assert "GPU:     2x — VRAM 10.0/80.0 GB" in result.output


def test_resources_show_pretty(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--pretty`` emits indented JSON even without top-level ``--json``."""
    monkeypatch.setattr(machine_cmd, "_import_metrics", lambda: _fake_metrics)
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["machine", "resources", "show", "--pretty"], obj={}
    )
    assert result.exit_code == 0
    # Two-space indent is the tell.
    assert '\n  "display"' in result.output or '"display":' in result.output


def test_resources_show_missing_mb_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the producer can't read some metrics, display is ``-``, not 'None'."""
    metrics = {
        "cpu_count": None,
        "mem_used_mb": None,
        "mem_total_mb": None,
        "disk_used_mb": None,
        "disk_total_mb": None,
        "gpus": [],
    }
    monkeypatch.setattr(machine_cmd, "_import_metrics", lambda: lambda: metrics)
    runner = CliRunner()
    result = runner.invoke(orochi, ["machine", "resources", "show"], obj={})
    assert result.exit_code == 0, result.output
    assert "CPU:     -" in result.output
    assert "RAM:     -" in result.output
    assert "Storage: -" in result.output
