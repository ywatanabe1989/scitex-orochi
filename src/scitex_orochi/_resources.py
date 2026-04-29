"""System resource metrics collection for Orochi heartbeats.

Cross-platform via :mod:`scitex_resource.get_metrics` (psutil-backed,
container-aware). Linux / macOS / Windows / WSL all return the same flat dict
shape, so heartbeats from any host populate the Machines tab consistently.

Slurm overlay (todo#87): when ``sinfo`` is on PATH the local login-node
CPU / RAM / GPU figures are replaced with cluster-aggregate values from
``sinfo``/``squeue`` and supplemental ``orochi_slurm_*`` keys are added.
The orochi_slurm call is best-effort and bounded at ~3 s per heartbeat;
any failure falls back silently to ``get_metrics()`` above.
"""

from __future__ import annotations

import logging

try:
    from scitex_resource import get_metrics as _get_metrics
    _GET_METRICS_AVAILABLE = True
except ImportError:
    # Older scitex_resource installs (< API with get_metrics). Return empty dict
    # so tests and local dev imports don't crash. Production always has the
    # published version with get_metrics.
    def _get_metrics():  # type: ignore[misc]
        return {}
    _GET_METRICS_AVAILABLE = False

log = logging.getLogger("orochi.resources")


def collect_metrics() -> dict[str, str | int | float | list]:
    """Collect system resource metrics for a heartbeat payload.

    Delegates to :func:`scitex_resource.get_metrics` for the cross-platform
    base dict, then overlays Slurm cluster aggregates on hosts that have
    ``sinfo`` on PATH.

    Returns
    -------
    dict
        Flat dict with keys: ``cpu_count``, ``cpu_model``,
        ``load_avg_1m/5m/15m``, ``mem_total_mb``, ``mem_used_mb``,
        ``mem_free_mb``, ``mem_used_percent``, ``disk_total_mb``,
        ``disk_used_mb``, ``disk_used_percent``, ``gpus``. On Slurm
        login nodes also: ``cluster_*`` and ``orochi_slurm_*`` keys.
    """
    metrics: dict[str, str | int | float | list] = dict(_get_metrics())

    try:
        from scitex_orochi._orochi_slurm import collect_orochi_slurm_metrics

        orochi_slurm_metrics = collect_orochi_slurm_metrics()
    except Exception:  # pragma: no cover - never break a heartbeat
        log.debug("Slurm metric collection raised", exc_info=True)
        orochi_slurm_metrics = {}
    if orochi_slurm_metrics:
        metrics.update(orochi_slurm_metrics)

    return metrics
