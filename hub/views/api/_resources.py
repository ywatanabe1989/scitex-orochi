"""``GET /api/resources`` — per-machine resource aggregation from the agent registry.

Split out of ``_agents.py`` so both sub-files stay under the 500-line
ceiling. The endpoint is conceptually about machine hardware (CPU,
memory, disk, Slurm cluster rollups), not about agent identity, so it
earns its own module.
"""

from hub.views.api._common import (
    JsonResponse,
    get_workspace,
    login_required,
    require_GET,
)


@login_required
@require_GET
def api_resources(request):
    """GET /api/resources — resource usage aggregated per machine from agent registry."""
    workspace = get_workspace(request)

    from hub.registry import get_agents

    agents = get_agents(workspace_id=workspace.id)

    # Aggregate by machine hostname (fall back to agent name)
    machines: dict[str, dict] = {}
    for a in agents:
        machine = a.get("machine") or a["name"]
        metrics = a.get("metrics") or {}

        if machine not in machines:
            machines[machine] = {
                "machine": machine,
                "status": a.get("status", "unknown"),
                "last_heartbeat": a.get("last_heartbeat"),
                "agents": [],
                "resources": {
                    "cpu_count": metrics.get("cpu_count", 0),
                    "cpu_model": metrics.get("cpu_model", ""),
                    "load_avg_1m": metrics.get("load_avg_1m", 0),
                    "load_avg_5m": metrics.get("load_avg_5m", 0),
                    "load_avg_15m": metrics.get("load_avg_15m", 0),
                    "mem_used_percent": metrics.get("mem_used_percent", 0),
                    "mem_total_mb": metrics.get("mem_total_mb", 0),
                    "mem_free_mb": metrics.get("mem_free_mb", 0),
                    # ywatanabe msg#16215 — absolute MB for the ``N/M GB``
                    # sidebar + tooltip display on mba/nas. Derive
                    # ``mem_used_mb`` from ``total - free`` when the
                    # producer didn't send it directly (pre-fix clients).
                    "mem_used_mb": metrics.get(
                        "mem_used_mb",
                        max(
                            0,
                            int(metrics.get("mem_total_mb", 0) or 0)
                            - int(metrics.get("mem_free_mb", 0) or 0),
                        ),
                    ),
                    "disk_used_percent": metrics.get("disk_used_percent", 0),
                    # ywatanabe msg#16215 — storage as ``N/M TB``. Older
                    # clients (before 2026-04-21) only sent percent, so
                    # default to 0 and the frontend falls back to ``—``.
                    "disk_total_mb": metrics.get("disk_total_mb", 0),
                    "disk_used_mb": metrics.get("disk_used_mb", 0),
                    # Per-GPU list for ``N/M`` GPU display + VRAM tooltip.
                    # Empty ``[]`` on GPU-less hosts (mba, nas) → frontend
                    # renders ``n/a`` per spec.
                    "gpus": list(metrics.get("gpus") or []),
                    # Slurm cluster aggregates (todo#87) — absent on non-slurm hosts
                    "resource_source": metrics.get("resource_source", "local"),
                    "cluster_nodes": metrics.get("cluster_nodes", 0),
                    "cluster_cpus_allocated": metrics.get("cluster_cpus_allocated", 0),
                    "cluster_cpus_total": metrics.get("cluster_cpus_total", 0),
                    "cluster_mem_free_mb": metrics.get("cluster_mem_free_mb", 0),
                    "cluster_mem_total_mb": metrics.get("cluster_mem_total_mb", 0),
                    "cluster_gpus_total": metrics.get("cluster_gpus_total", 0),
                    "cluster_gpus_allocated": metrics.get("cluster_gpus_allocated", 0),
                    "slurm_total_jobs": metrics.get("slurm_total_jobs", 0),
                    "slurm_running": metrics.get("slurm_running", 0),
                    "slurm_pending": metrics.get("slurm_pending", 0),
                },
            }

        machines[machine]["agents"].append(a["name"])

        # Update with latest metrics if this agent has fresher data
        if metrics and a.get("status") == "online":
            res = machines[machine]["resources"]
            for key in (
                "cpu_count",
                "cpu_model",
                "load_avg_1m",
                "load_avg_5m",
                "load_avg_15m",
                "mem_used_percent",
                "mem_total_mb",
                "mem_free_mb",
                "mem_used_mb",
                "disk_used_percent",
                "disk_total_mb",
                "disk_used_mb",
                "resource_source",
                "cluster_nodes",
                "cluster_cpus_allocated",
                "cluster_cpus_total",
                "cluster_mem_free_mb",
                "cluster_mem_total_mb",
                "cluster_gpus_total",
                "cluster_gpus_allocated",
                "slurm_total_jobs",
                "slurm_running",
                "slurm_pending",
            ):
                val = metrics.get(key)
                if val:
                    res[key] = val
            # ``gpus`` is a list — ``if val:`` correctly skips ``[]``
            # (GPU-less hosts) so a later agent without a GPU doesn't
            # clobber a previously-observed GPU list. Non-empty wins.
            if metrics.get("gpus"):
                res["gpus"] = list(metrics["gpus"])
            # ywatanabe msg#16215 derive-on-aggregate fallback: pre-fix
            # clients only sent ``mem_total_mb`` + ``mem_free_mb`` (no
            # ``mem_used_mb``). Compute it here so the N/M GB frontend
            # renderer doesn't show ``—`` during the rolling deploy
            # window where some hosts are updated and some aren't.
            if not res.get("mem_used_mb"):
                total = int(res.get("mem_total_mb") or 0)
                free = int(res.get("mem_free_mb") or 0)
                if total:
                    res["mem_used_mb"] = max(0, total - free)
            # Prefer online status
            machines[machine]["status"] = "online"
            if a.get("last_heartbeat"):
                machines[machine]["last_heartbeat"] = a["last_heartbeat"]

    return JsonResponse(machines, safe=False)
