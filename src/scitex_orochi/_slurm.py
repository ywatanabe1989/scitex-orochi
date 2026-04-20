"""Slurm cluster-resource collection for heartbeats (todo#87).

When a heartbeat-emitting agent runs on a Slurm login node, reporting local
``top``/``free`` numbers is misleading — the login node's CPU and RAM are
not what a user of the cluster actually has available. This module shells
out to ``sinfo`` / ``squeue`` and returns *cluster-aggregate* metrics so
that the Machines tab can display "what Slurm says is free/busy".

Design principle: best-effort and side-effect-free.

- All subprocess calls are bounded by ``SLURM_TIMEOUT_S`` (default 3s). On
  timeout, missing binary, or any parse error, the helpers return an
  empty dict and the caller falls back to local ``/proc`` metrics.
- Output is normalised to the same keys as ``_resources.collect_metrics``
  so the server's ``_RESOURCE_KEYS`` filter and the Machines tab UI need
  no further changes to render slurm-hosted aggregates.
- Additional slurm-only fields (``slurm_total_jobs``, ``slurm_running``,
  ``slurm_pending``, ``cluster_cpus_total`` …) are reported alongside the
  overridden standard fields and are persisted by the hub once their keys
  are added to ``_server._RESOURCE_KEYS``.

This lives deliberately close to ``_resources.py`` rather than inside the
richer ``host-telemetry-probe.sh`` / ``slurm-resource-scraper`` contract
daemon (see ``_skills/scitex-orochi/slurm-resource-scraper-contract.md``)
because the Machines tab only needs a small aggregate — not verbatim
stdout — and a lightweight override on the heartbeat path avoids a new
daemon, a new hub consumer, and a new channel subscription.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

log = logging.getLogger("orochi.slurm")

SLURM_TIMEOUT_S = 3.0


def _run(cmd: list[str]) -> str | None:
    """Run a slurm CLI command with a hard timeout.

    Returns stdout text on success, ``None`` on missing binary, timeout,
    non-zero exit, or any subprocess error.
    """
    if not cmd:
        return None
    if shutil.which(cmd[0]) is None:
        return None
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SLURM_TIMEOUT_S,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("Slurm cmd %s failed: %s", cmd, exc)
        return None
    if proc.returncode != 0:
        log.debug(
            "Slurm cmd %s exit=%s stderr=%s",
            cmd,
            proc.returncode,
            (proc.stderr or "").strip()[:200],
        )
        return None
    return proc.stdout


def has_slurm() -> bool:
    """True iff ``sinfo`` is on PATH. Cheap, non-executing probe."""
    return shutil.which("sinfo") is not None


def _parse_cpus_aiot(token: str) -> tuple[int, int] | None:
    """Parse ``A/I/O/T`` CPU token into ``(allocated, total)``.

    Slurm ``%C`` format renders per-row CPU counts as
    ``Allocated/Idle/Other/Total``.
    """
    parts = token.split("/")
    if len(parts) != 4:
        return None
    try:
        allocated = int(parts[0])
        total = int(parts[3])
    except ValueError:
        return None
    if total <= 0:
        return None
    return allocated, total


def _parse_gres_gpu_count(token: str) -> int:
    """Return total GPU count declared in a GRES / TRES cell.

    Accepts both the ``sinfo %G`` style (``gpu:a100:8``) and the
    ``squeue %b`` / ``scontrol`` style (``gres:gpu:2``).

    Examples:
        ``(null)`` -> 0
        ``gpu:a100:8`` -> 8
        ``gpu:8`` -> 8
        ``gpu:a100:4,gpu:h100:2`` -> 6
        ``gres:gpu:2`` -> 2
        ``gpu:a100:4(S:0-1)`` -> 4
    """
    if not token or token in ("(null)", "N/A", ""):
        return 0
    total = 0
    for entry in token.split(","):
        entry = entry.strip()
        if "gpu" not in entry.lower():
            continue
        # Strip any parenthesised suffix such as "(S:0-1)" first, then
        # take the last ":"-delimited field as the count.
        head = entry.split("(", 1)[0].strip()
        tail = head.split(":")[-1].strip()
        try:
            total += int(tail)
        except ValueError:
            continue
    return total


def _collect_sinfo_aggregate() -> dict[str, Any]:
    """Aggregate ``sinfo`` rows into cluster-wide CPU / RAM / GPU totals.

    Uses ``-N`` (one row per node) and ``-h`` (no header) with a fixed
    format string so downstream parsing is robust against column-width
    changes. Nodes appearing in multiple partitions are de-duplicated by
    node name.
    """
    # %n=nodename %C=CPUs(A/I/O/T) %e=free_mem_mb %m=total_mem_mb %G=GRES
    stdout = _run(["sinfo", "-N", "-h", "-o", "%n|%C|%e|%m|%G"])
    if not stdout:
        return {}

    nodes: dict[str, dict[str, int]] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        fields = line.split("|")
        if len(fields) < 5:
            continue
        nodename, cpus_tok, free_mem_tok, total_mem_tok, gres_tok = (
            fields[0],
            fields[1],
            fields[2],
            fields[3],
            fields[4],
        )
        if not nodename:
            continue
        aiot = _parse_cpus_aiot(cpus_tok)
        if aiot is None:
            continue
        allocated, total_cpus = aiot

        # Memory cells may be "N/A" or trailing "+" for heterogeneous nodes
        def _to_int(s: str) -> int:
            s = (s or "").strip().rstrip("+")
            try:
                return int(s)
            except ValueError:
                return 0

        free_mem = _to_int(free_mem_tok)
        total_mem = _to_int(total_mem_tok)
        gpus_total = _parse_gres_gpu_count(gres_tok)

        # De-duplicate: first occurrence of nodename wins (values are per
        # node and should be identical across partitions).
        if nodename in nodes:
            continue
        nodes[nodename] = {
            "cpus_allocated": allocated,
            "cpus_total": total_cpus,
            "mem_free_mb": free_mem,
            "mem_total_mb": total_mem,
            "gpus_total": gpus_total,
        }

    if not nodes:
        return {}

    cpus_alloc = sum(n["cpus_allocated"] for n in nodes.values())
    cpus_total = sum(n["cpus_total"] for n in nodes.values())
    mem_free = sum(n["mem_free_mb"] for n in nodes.values())
    mem_total = sum(n["mem_total_mb"] for n in nodes.values())
    gpus_total = sum(n["gpus_total"] for n in nodes.values())

    agg: dict[str, Any] = {
        "cluster_nodes": len(nodes),
        "cluster_cpus_allocated": cpus_alloc,
        "cluster_cpus_total": cpus_total,
        "cluster_mem_free_mb": mem_free,
        "cluster_mem_total_mb": mem_total,
        "cluster_gpus_total": gpus_total,
    }
    return agg


def _collect_squeue_jobs() -> dict[str, Any]:
    """Count jobs and sum allocated GPUs from ``squeue``."""
    # %T=state %C=cpus-per-job %b=tres_per_node (e.g. gres:gpu:2)
    stdout = _run(["squeue", "-h", "-a", "-o", "%T|%C|%b"])
    if stdout is None:
        return {}

    total = 0
    running = 0
    pending = 0
    gpus_allocated = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        fields = line.split("|")
        if len(fields) < 3:
            continue
        state, _cpus_tok, tres_tok = fields[0], fields[1], fields[2]
        total += 1
        s = state.upper()
        if s == "RUNNING":
            running += 1
            # Only count GPUs for active allocations
            gpus_allocated += _parse_gres_gpu_count(tres_tok)
        elif s == "PENDING":
            pending += 1

    return {
        "slurm_total_jobs": total,
        "slurm_running": running,
        "slurm_pending": pending,
        "cluster_gpus_allocated": gpus_allocated,
    }


def collect_slurm_metrics() -> dict[str, Any]:
    """Return normalised cluster metrics, or an empty dict on any failure.

    Keys overlap with ``_resources.collect_metrics``:

    - ``cpu_count``, ``mem_total_mb``, ``mem_free_mb``, ``mem_used_percent``

    and add slurm-specific keys:

    - ``cluster_nodes``, ``cluster_cpus_allocated``, ``cluster_cpus_total``
    - ``cluster_mem_total_mb``, ``cluster_mem_free_mb``
    - ``cluster_gpus_total``, ``cluster_gpus_allocated``
    - ``slurm_total_jobs``, ``slurm_running``, ``slurm_pending``
    - ``resource_source = "slurm"``

    A ``load_avg_*`` value is synthesised as ``cpus_allocated`` so the
    existing Machines tab CPU% bar (computed from load / cpu_count) tracks
    cluster utilisation instead of login-node load.
    """
    if not has_slurm():
        return {}

    agg = _collect_sinfo_aggregate()
    if not agg:
        return {}

    cpus_alloc = agg["cluster_cpus_allocated"]
    cpus_total = agg["cluster_cpus_total"]
    mem_free = agg["cluster_mem_free_mb"]
    mem_total = agg["cluster_mem_total_mb"]

    out: dict[str, Any] = dict(agg)
    out["resource_source"] = "slurm"

    # Override scalar "machine" metrics with cluster-wide values
    if cpus_total > 0:
        out["cpu_count"] = cpus_total
        # Synthesise a load_avg that matches cluster allocation so the
        # existing CPU% visualisation (load/cpu_count) shows cluster busy%.
        out["load_avg_1m"] = float(cpus_alloc)
        out["load_avg_5m"] = float(cpus_alloc)
        out["load_avg_15m"] = float(cpus_alloc)
    if mem_total > 0:
        out["mem_total_mb"] = mem_total
        out["mem_free_mb"] = mem_free
        out["mem_used_percent"] = round((1 - mem_free / mem_total) * 100, 1)

    jobs = _collect_squeue_jobs()
    if jobs:
        out.update(jobs)

    return out
