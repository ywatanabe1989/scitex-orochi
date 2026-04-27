"""Base types and helpers shared across the Orochi server package."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [orochi] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("orochi")


def _log_task_exception(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    """Log exceptions from fire-and-forget tasks instead of silently dropping them."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("Background task failed: %s", exc, exc_info=exc)


@dataclass
class Agent:
    name: str
    ws: Any  # ServerConnection
    channels: set[str] = field(default_factory=set)
    orochi_machine: str = ""
    role: str = ""
    model: str = ""
    agent_id: str = ""
    project: str = ""
    workspace_id: str = ""
    multiplexer: str = ""
    status: str = "online"
    orochi_current_task: str = ""
    orochi_subagent_count: int = 0
    resources: dict[str, Any] = field(default_factory=dict)
    last_heartbeat: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    registered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# Resource metric keys accepted from agent heartbeats. Slurm cluster aggregates
# (todo#87) are present only on hosts where ``sinfo`` is on PATH; absent keys
# are ignored downstream.
RESOURCE_KEYS: set[str] = {
    "cpu_count",
    "cpu_model",
    "load_avg_1m",
    "load_avg_5m",
    "load_avg_15m",
    "mem_free_mb",
    "mem_total_mb",
    "mem_used_percent",
    "disk_used_percent",
    "resource_source",
    "cluster_nodes",
    "cluster_cpus_allocated",
    "cluster_cpus_total",
    "cluster_mem_free_mb",
    "cluster_mem_total_mb",
    "cluster_gpus_total",
    "cluster_gpus_allocated",
    "orochi_slurm_total_jobs",
    "orochi_slurm_running",
    "orochi_slurm_pending",
}
