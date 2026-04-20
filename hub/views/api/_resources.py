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
                    "disk_used_percent": metrics.get("disk_used_percent", 0),
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
                "disk_used_percent",
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
            # Prefer online status
            machines[machine]["status"] = "online"
            if a.get("last_heartbeat"):
                machines[machine]["last_heartbeat"] = a["last_heartbeat"]

    return JsonResponse(machines, safe=False)
