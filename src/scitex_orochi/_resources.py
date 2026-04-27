"""System resource metrics collection for Orochi heartbeats.

Collects CPU, memory, disk, and load metrics using /proc and os module.
No external dependencies (psutil not required).

Slurm override (todo#87): when the host has ``sinfo`` on PATH, the local
login-node CPU / RAM / GPU figures are replaced with cluster-aggregate
values from ``sinfo``/``squeue`` so the Machines tab shows actual
available compute rather than the login node's snapshot. See
``_orochi_slurm.collect_orochi_slurm_metrics``. The orochi_slurm call is best-effort and
bounded at ~3s per heartbeat; any failure falls back silently to the
``/proc`` metrics collected above.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("orochi.resources")


def collect_metrics() -> dict[str, str | int | float]:
    """Collect system resource metrics.

    Returns dict with keys matching _RESOURCE_KEYS in _server.py:
        cpu_count, cpu_model, load_avg_1m, load_avg_5m, load_avg_15m,
        mem_free_mb, mem_total_mb, mem_used_percent, disk_used_percent

    On Slurm hosts (``sinfo`` on PATH), CPU / RAM / GPU fields are
    overridden with cluster aggregates and supplemental orochi_slurm keys
    (``orochi_slurm_total_jobs``, ``cluster_cpus_total`` …) are appended.
    """
    metrics: dict[str, str | int | float] = {}

    # CPU count
    cpu_count = os.cpu_count()
    if cpu_count is not None:
        metrics["cpu_count"] = cpu_count

    # CPU orochi_model from /proc/cpuinfo
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        for line in cpuinfo.splitlines():
            if line.startswith("orochi_model name"):
                metrics["cpu_model"] = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass

    # Load averages
    try:
        load1, load5, load15 = os.getloadavg()
        metrics["load_avg_1m"] = round(load1, 2)
        metrics["load_avg_5m"] = round(load5, 2)
        metrics["load_avg_15m"] = round(load15, 2)
    except OSError:
        pass

    # Memory from /proc/meminfo
    try:
        meminfo = Path("/proc/meminfo").read_text()
        mem = {}
        for line in meminfo.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                mem[key] = int(parts[1])  # in kB

        if "MemTotal" in mem:
            total_mb = mem["MemTotal"] // 1024
            metrics["mem_total_mb"] = total_mb

            # Use MemAvailable if present (Linux 3.14+), else MemFree
            free_kb = mem.get("MemAvailable", mem.get("MemFree", 0))
            free_mb = free_kb // 1024
            metrics["mem_free_mb"] = free_mb

            if total_mb > 0:
                used_pct = round((1 - free_mb / total_mb) * 100, 1)
                metrics["mem_used_percent"] = used_pct
    except (OSError, ValueError):
        pass

    # Disk usage for root partition
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if total > 0:
            used_pct = round((1 - free / total) * 100, 1)
            metrics["disk_used_percent"] = used_pct
    except OSError:
        pass

    # Slurm override for cluster login nodes (todo#87). Runs last so any
    # parsing failure leaves the /proc-based metrics intact. Disk is left
    # untouched because Slurm doesn't track shared-fs usage.
    try:
        from scitex_orochi._orochi_slurm import collect_orochi_slurm_metrics

        orochi_slurm_metrics = collect_orochi_slurm_metrics()
    except Exception:  # pragma: no cover - defensive: never break heartbeat
        log.debug("Slurm metric collection raised", exc_info=True)
        orochi_slurm_metrics = {}
    if orochi_slurm_metrics:
        metrics.update(orochi_slurm_metrics)

    return metrics
