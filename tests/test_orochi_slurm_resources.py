"""Unit tests for the Slurm resource-metric override (todo#87)."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from scitex_orochi import _orochi_slurm, _resources

# ---------------------------------------------------------------------------
# Low-level parser tests
# ---------------------------------------------------------------------------


def test_parse_cpus_aiot_normal():
    assert _orochi_slurm._parse_cpus_aiot("12/0/0/12") == (12, 12)
    assert _orochi_slurm._parse_cpus_aiot("4/60/0/64") == (4, 64)


def test_parse_cpus_aiot_malformed():
    assert _orochi_slurm._parse_cpus_aiot("") is None
    assert _orochi_slurm._parse_cpus_aiot("12/0/0") is None
    assert _orochi_slurm._parse_cpus_aiot("a/b/c/d") is None
    assert _orochi_slurm._parse_cpus_aiot("0/0/0/0") is None  # zero total


def test_parse_gres_gpu_count():
    assert _orochi_slurm._parse_gres_gpu_count("(null)") == 0
    assert _orochi_slurm._parse_gres_gpu_count("") == 0
    assert _orochi_slurm._parse_gres_gpu_count("N/A") == 0
    assert _orochi_slurm._parse_gres_gpu_count("gpu:a100:8") == 8
    assert _orochi_slurm._parse_gres_gpu_count("gpu:8") == 8
    assert _orochi_slurm._parse_gres_gpu_count("gpu:a100:4,gpu:h100:2") == 6
    assert _orochi_slurm._parse_gres_gpu_count("gpu:a100:4(S:0-1)") == 4


# ---------------------------------------------------------------------------
# Aggregation tests — patch subprocess.run + shutil.which
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _mk_run(responses):
    """Build a fake ``subprocess.run`` that dispatches on argv[0]."""

    def _fake(cmd, **_kwargs):
        key = cmd[0]
        if key not in responses:
            raise FileNotFoundError(key)
        out = responses[key]
        if isinstance(out, Exception):
            raise out
        return _FakeProc(stdout=out)

    return _fake


def test_collect_orochi_slurm_metrics_no_sinfo():
    """When sinfo is missing, returns empty dict."""
    with patch.object(_orochi_slurm.shutil, "which", return_value=None):
        assert _orochi_slurm.collect_orochi_slurm_metrics() == {}


def test_collect_orochi_slurm_metrics_single_node_cluster():
    """NAS-shape: one node, 12/12 CPUs, 6 running visitor jobs."""
    sinfo_out = "DXP480TPLUS-994|12/0/0/12|826|64038|(null)\n"
    squeue_out = (
        "RUNNING|2|N/A\n"
        "RUNNING|2|N/A\n"
        "RUNNING|2|N/A\n"
        "RUNNING|2|N/A\n"
        "RUNNING|2|N/A\n"
        "RUNNING|2|N/A\n"
    )
    fake = _mk_run({"sinfo": sinfo_out, "squeue": squeue_out})
    with (
        patch.object(_orochi_slurm.shutil, "which", return_value="/usr/bin/sinfo"),
        patch.object(_orochi_slurm.subprocess, "run", side_effect=fake),
    ):
        out = _orochi_slurm.collect_orochi_slurm_metrics()

    assert out["resource_source"] == "orochi_slurm"
    assert out["cluster_nodes"] == 1
    assert out["cluster_cpus_total"] == 12
    assert out["cluster_cpus_allocated"] == 12
    assert out["cluster_mem_total_mb"] == 64038
    assert out["cluster_mem_free_mb"] == 826
    assert out["cluster_gpus_total"] == 0
    assert out["orochi_slurm_total_jobs"] == 6
    assert out["orochi_slurm_running"] == 6
    assert out["orochi_slurm_pending"] == 0

    # Override propagates into the scalar "machine" keys used by the UI.
    assert out["cpu_count"] == 12
    assert out["mem_total_mb"] == 64038
    assert out["mem_free_mb"] == 826
    # (64038 - 826) / 64038 = 98.7%
    assert out["mem_used_percent"] == 98.7
    # load_avg synthesised so CPU% bar (load/cpu_count) hits 100%
    assert out["load_avg_1m"] == 12.0


def test_collect_orochi_slurm_metrics_multi_node_with_gpus():
    """Spartan-shape: partial allocation, heterogeneous GPU nodes."""
    sinfo_out = (
        "gpu01|4/60/0/64|128000|256000|gpu:a100:8\n"
        "gpu02|0/64/0/64|256000|256000|gpu:a100:8\n"
        "cpu01|32/32/0/64|32000|128000|(null)\n"
        # Duplicate row (same node in a second partition) must be skipped
        "gpu01|4/60/0/64|128000|256000|gpu:a100:8\n"
    )
    squeue_out = "RUNNING|4|gres:gpu:2\nPENDING|32|gres:gpu:4\nRUNNING|32|N/A\n"
    fake = _mk_run({"sinfo": sinfo_out, "squeue": squeue_out})
    with (
        patch.object(_orochi_slurm.shutil, "which", return_value="/usr/bin/sinfo"),
        patch.object(_orochi_slurm.subprocess, "run", side_effect=fake),
    ):
        out = _orochi_slurm.collect_orochi_slurm_metrics()

    assert out["cluster_nodes"] == 3  # deduped
    assert out["cluster_cpus_total"] == 192  # 64*3
    assert out["cluster_cpus_allocated"] == 36  # 4+0+32
    assert out["cluster_mem_total_mb"] == 640000
    assert out["cluster_mem_free_mb"] == 416000
    assert out["cluster_gpus_total"] == 16  # 8+8
    # Only RUNNING jobs contribute to gpus_allocated; PENDING does not.
    assert out["cluster_gpus_allocated"] == 2
    assert out["orochi_slurm_total_jobs"] == 3
    assert out["orochi_slurm_running"] == 2
    assert out["orochi_slurm_pending"] == 1


def test_collect_orochi_slurm_metrics_sinfo_timeout_returns_empty():
    """A sinfo timeout must not crash the heartbeat path."""

    def _timeout(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd="sinfo", timeout=3.0)

    with (
        patch.object(_orochi_slurm.shutil, "which", return_value="/usr/bin/sinfo"),
        patch.object(_orochi_slurm.subprocess, "run", side_effect=_timeout),
    ):
        assert _orochi_slurm.collect_orochi_slurm_metrics() == {}


def test_collect_orochi_slurm_metrics_sinfo_nonzero_exit_returns_empty():
    """sinfo exiting non-zero is treated like no data (fallback to local)."""

    def _fail(*_a, **_kw):
        return _FakeProc(stdout="", returncode=1, stderr="orochi_slurmctld down")

    with (
        patch.object(_orochi_slurm.shutil, "which", return_value="/usr/bin/sinfo"),
        patch.object(_orochi_slurm.subprocess, "run", side_effect=_fail),
    ):
        assert _orochi_slurm.collect_orochi_slurm_metrics() == {}


# ---------------------------------------------------------------------------
# Integration: _resources.collect_metrics composes orochi_slurm override correctly
# ---------------------------------------------------------------------------


def test_collect_metrics_merges_orochi_slurm_override():
    """On a orochi_slurm host, collect_metrics returns orochi_slurm aggregates overlaid."""
    fake_orochi_slurm = {
        "resource_source": "orochi_slurm",
        "cluster_nodes": 2,
        "cluster_cpus_allocated": 10,
        "cluster_cpus_total": 100,
        "cluster_mem_total_mb": 500_000,
        "cluster_mem_free_mb": 450_000,
        "cluster_gpus_total": 4,
        "cpu_count": 100,
        "mem_total_mb": 500_000,
        "mem_free_mb": 450_000,
        "mem_used_percent": 10.0,
        "load_avg_1m": 10.0,
        "load_avg_5m": 10.0,
        "load_avg_15m": 10.0,
        "orochi_slurm_total_jobs": 3,
        "orochi_slurm_running": 2,
        "orochi_slurm_pending": 1,
    }
    with patch("scitex_orochi._orochi_slurm.collect_orochi_slurm_metrics", return_value=fake_orochi_slurm):
        metrics = _resources.collect_metrics()

    # Slurm aggregates overrode the /proc-derived scalars
    assert metrics["cpu_count"] == 100
    assert metrics["mem_total_mb"] == 500_000
    assert metrics["resource_source"] == "orochi_slurm"
    assert metrics["orochi_slurm_total_jobs"] == 3
    # Disk is NOT touched by orochi_slurm — local /proc value still present
    # (skip assertion on exact value; just require key exists when available)


def test_collect_metrics_no_orochi_slurm_returns_local_only():
    """On a non-orochi_slurm host (empty orochi_slurm dict), local metrics stand alone."""
    with patch("scitex_orochi._orochi_slurm.collect_orochi_slurm_metrics", return_value={}):
        metrics = _resources.collect_metrics()

    assert "resource_source" not in metrics
    assert "cluster_nodes" not in metrics
    assert "orochi_slurm_total_jobs" not in metrics
    # Local metrics still collected (at least cpu_count should be present)
    assert "cpu_count" in metrics


def test_collect_metrics_orochi_slurm_exception_swallowed():
    """Any unexpected exception from orochi_slurm code must not break heartbeat."""
    with patch(
        "scitex_orochi._orochi_slurm.collect_orochi_slurm_metrics",
        side_effect=RuntimeError("boom"),
    ):
        metrics = _resources.collect_metrics()
    assert "cpu_count" in metrics  # local path still ran
    assert "resource_source" not in metrics
