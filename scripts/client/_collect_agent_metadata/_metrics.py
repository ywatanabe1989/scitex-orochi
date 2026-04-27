"""Cross-OS host resource metrics + SLURM snapshot (todo#329 / todo#59)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from typing import Any


def collect_machine_metrics() -> dict:
    """Cross-OS host resource snapshot for the Orochi Machines tab (todo#329).

    Reads CPU/memory/disk/load via psutil if available; falls back to a
    minimal stdlib best-effort if psutil is missing. Output keys match
    what ``hub/views/api.py:api_resources`` projects into the per-orochi_machine
    Machines tab card. Empty/None on any read error so the receiver
    degrades gracefully.

    Target display shape (ywatanabe msg#16215):

    - CPU: ``N cores`` — ``cpu_count`` as integer
    - RAM: ``N/M GB`` — ``mem_used_mb`` / ``mem_total_mb`` (MB; hub divides)
    - Storage: ``N/M TB`` — ``disk_used_mb`` / ``disk_total_mb``
    - GPU: ``N/M`` — per-GPU ``utilization_percent`` + ``memory_*_mb`` in ``gpus``

    ``disk_total_mb`` / ``disk_used_mb`` / ``gpus`` were added post
    msg#16215 because the hub sidebar + Machines-tab tooltip were
    rendering empty strings for mba + nas (no GPU hosts): the legacy
    producer emitted only ``disk_used_percent`` and no GPU info, so the
    aggregator in ``hub/views/api/_resources.py`` had no "total" side
    for the N/M storage display.
    """
    out: dict[str, Any] = {
        "cpu_count": None,
        "cpu_model": "",
        "load_avg_1m": None,
        "load_avg_5m": None,
        "load_avg_15m": None,
        "mem_used_percent": None,
        "mem_total_mb": None,
        "mem_free_mb": None,
        "mem_used_mb": None,
        "disk_used_percent": None,
        "disk_total_mb": None,
        "disk_used_mb": None,
        # Per-GPU list — empty on hosts without a GPU. Each entry carries
        # enough for the hub's ``N/M GPU`` + VRAM tooltip (utilization_%,
        # memory_used_mb, memory_total_mb, name).
        "gpus": [],
    }
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None  # type: ignore

    try:
        if psutil is not None:
            out["cpu_count"] = psutil.cpu_count(logical=True)
        else:
            out["cpu_count"] = os.cpu_count()
    except Exception:
        pass

    try:
        if hasattr(os, "getloadavg"):
            l1, l5, l15 = os.getloadavg()
            out["load_avg_1m"] = round(l1, 2)
            out["load_avg_5m"] = round(l5, 2)
            out["load_avg_15m"] = round(l15, 2)
    except Exception:
        pass

    # Memory: try psutil first, then stdlib /proc/meminfo (Linux), then
    # /usr/sbin/sysctl + vm_stat (Darwin). psutil is not always installed
    # in the python3 PATH the heartbeat shell-out picks (the bun MCP
    # sidecar inherits whatever PATH is active in the agent's tmux pane —
    # if that's a non-venv shell, psutil import fails and we'd lose all
    # mem fields without this fallback).
    try:
        if psutil is not None:
            vm = psutil.virtual_memory()
            out["mem_total_mb"] = int(vm.total / 1024 / 1024)
            out["mem_free_mb"] = int(
                vm.available / 1024 / 1024
            )  # use "available", not "free" — Darwin/Linux semantics (todo#310)
            out["mem_used_mb"] = int((vm.total - vm.available) / 1024 / 1024)
            out["mem_used_percent"] = round(
                (vm.total - vm.available) * 100.0 / max(vm.total, 1), 1
            )
        else:
            raise ImportError
    except Exception:
        try:
            if sys.platform.startswith("linux"):
                with open("/proc/meminfo") as f:
                    kv: dict[str, int] = {}
                    for ln in f:
                        m = re.match(r"(\w+):\s+(\d+)\s*kB", ln)
                        if m:
                            kv[m.group(1)] = int(m.group(2)) * 1024
                total = kv.get("MemTotal")
                avail = kv.get("MemAvailable", kv.get("MemFree"))
                if total and avail is not None:
                    out["mem_total_mb"] = int(total / 1024 / 1024)
                    out["mem_free_mb"] = int(avail / 1024 / 1024)
                    out["mem_used_mb"] = int((total - avail) / 1024 / 1024)
                    out["mem_used_percent"] = round(
                        (total - avail) * 100.0 / max(total, 1), 1
                    )
            elif sys.platform == "darwin":
                import subprocess as _sp

                total_bytes = int(
                    _sp.check_output(
                        ["/usr/sbin/sysctl", "-n", "hw.memsize"], text=True
                    ).strip()
                )
                vm_out = _sp.check_output(["vm_stat"], text=True)
                page_size = 4096
                mp = re.search(r"page size of (\d+) bytes", vm_out)
                if mp:
                    page_size = int(mp.group(1))
                pages: dict[str, int] = {}
                for ln in vm_out.splitlines():
                    mm = re.match(r"(.+?):\s+(\d+)", ln)
                    if mm:
                        pages[mm.group(1).strip()] = int(mm.group(2))
                # Darwin: free + inactive + speculative (todo#310)
                free_bytes = (
                    pages.get("Pages free", 0)
                    + pages.get("Pages inactive", 0)
                    + pages.get("Pages speculative", 0)
                ) * page_size
                out["mem_total_mb"] = int(total_bytes / 1024 / 1024)
                out["mem_free_mb"] = int(free_bytes / 1024 / 1024)
                out["mem_used_mb"] = int((total_bytes - free_bytes) / 1024 / 1024)
                out["mem_used_percent"] = round(
                    (total_bytes - free_bytes) * 100.0 / max(total_bytes, 1), 1
                )
        except Exception:
            pass

    # Disk: try psutil, then statvfs. Emit BOTH percent AND absolute
    # total/used so the hub can render ``N/M TB`` (ywatanabe msg#16215).
    # The legacy-only percent field is kept for backwards compat with
    # older hub aggregators + the donut-chart renderer.
    try:
        if psutil is not None:
            du = psutil.disk_usage(os.path.expanduser("~"))
            out["disk_used_percent"] = round(du.percent, 1)
            out["disk_total_mb"] = int(du.total / 1024 / 1024)
            out["disk_used_mb"] = int(du.used / 1024 / 1024)
        else:
            raise ImportError
    except Exception:
        try:
            st = os.statvfs(os.path.expanduser("~"))
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = total - free
            if total > 0:
                out["disk_used_percent"] = round(used * 100.0 / total, 1)
                out["disk_total_mb"] = int(total / 1024 / 1024)
                out["disk_used_mb"] = int(used / 1024 / 1024)
        except Exception:
            pass

    # GPU: best-effort nvidia-smi query. Apple Silicon (mba) + NAS
    # (DXP480TPLUS) have no NVIDIA GPU — `shutil.which` returns None,
    # so ``gpus`` stays ``[]`` and the frontend renders "n/a" (spec).
    try:
        out["gpus"] = _collect_gpus()
    except Exception:
        out["gpus"] = []

    try:
        # cpu_model — best-effort, OS-specific
        import platform

        out["cpu_model"] = platform.processor() or ""
    except Exception:
        pass

    return out


def _collect_gpus() -> list[dict]:
    """Per-GPU snapshot via ``nvidia-smi``.

    Returns ``[]`` on hosts without ``nvidia-smi`` on PATH (Apple
    Silicon, NAS, any container without GPU pass-through). Each entry:
    ``{name, utilization_percent, memory_used_mb, memory_total_mb}``.

    Format chosen so ``hub/views/api/_resources.py`` can surface ``N/M``
    (GPU utilisation / GPU count) and ``VRAM used/total`` in the
    Machines-tab tooltip without further parsing.
    """
    if shutil.which("nvidia-smi") is None:
        return []
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    gpus: list[dict] = []
    for raw in proc.stdout.splitlines():
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) < 4:
            continue
        try:
            gpus.append(
                {
                    "name": parts[0],
                    "utilization_percent": float(parts[1]),
                    "memory_used_mb": float(parts[2]),
                    "memory_total_mb": float(parts[3]),
                }
            )
        except (ValueError, TypeError):
            continue
    return gpus


def collect_orochi_slurm_status():
    """Snapshot of SLURM compute resources for HPC hosts (todo#59).

    Returns ``None`` on hosts where SLURM is not installed (most fleet
    nodes), so the receiver can hide the SLURM card cleanly. On hosts
    where ``squeue`` and ``sinfo`` exist, returns a compact dict that
    the dashboard can render without further parsing::

        {
          "running_jobs":     int,         # squeue -t R for current user
          "pending_jobs":     int,         # squeue -t PD for current user
          "running_job_ids":  [str, ...],  # up to 5 most recent
          "running_partitions": [str, ...],
          "running_nodes":      [str, ...],
          "partitions":       {            # sinfo summary, top 4 partitions
              "<name>": {"idle": int, "alloc": int, "down": int, "total": int},
              ...
          },
          "user":             str,
        }

    All fields are best-effort; per-source try/except so that a stray
    line in ``squeue`` output never breaks the heartbeat. The whole
    snapshot is bounded — never more than ~5 jobs and 4 partitions —
    so it cannot bloat the WS message.
    """
    if shutil.which("squeue") is None:
        return None

    out: dict[str, Any] = {
        "running_jobs": 0,
        "pending_jobs": 0,
        "running_job_ids": [],
        "running_partitions": [],
        "running_nodes": [],
        "partitions": {},
        "user": os.environ.get("USER", ""),
    }

    user = out["user"]
    try:
        proc = subprocess.run(
            [
                "squeue",
                "-u",
                user,
                "-h",
                "-o",
                "%i|%P|%T|%R",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if proc.returncode == 0:
            running_ids: list[str] = []
            running_parts: list[str] = []
            running_nodes: list[str] = []
            r_count = 0
            p_count = 0
            for raw in proc.stdout.splitlines():
                parts = raw.strip().split("|")
                if len(parts) < 4:
                    continue
                jid, part, state, nodelist = parts[:4]
                if state == "RUNNING":
                    r_count += 1
                    if len(running_ids) < 5:
                        running_ids.append(jid)
                        running_parts.append(part)
                        running_nodes.append(nodelist)
                elif state == "PENDING":
                    p_count += 1
            out["running_jobs"] = r_count
            out["pending_jobs"] = p_count
            out["running_job_ids"] = running_ids
            out["running_partitions"] = running_parts
            out["running_nodes"] = running_nodes
    except Exception:
        pass

    if shutil.which("sinfo") is not None:
        try:
            proc = subprocess.run(
                [
                    "sinfo",
                    "-h",
                    "-o",
                    "%P %T %D",
                ],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if proc.returncode == 0:
                table: dict[str, dict[str, int]] = {}
                for raw in proc.stdout.splitlines():
                    fields = raw.split()
                    if len(fields) < 3:
                        continue
                    part_name, state, count_str = fields[0], fields[1], fields[2]
                    part_name = part_name.rstrip("*")
                    try:
                        count = int(count_str)
                    except ValueError:
                        continue
                    bucket = table.setdefault(
                        part_name,
                        {
                            "idle": 0,
                            "alloc": 0,
                            "down": 0,
                            "total": 0,
                        },
                    )
                    bucket["total"] += count
                    if state == "idle":
                        bucket["idle"] += count
                    elif state in ("allocated", "mixed", "completing"):
                        bucket["alloc"] += count
                    elif state in (
                        "down",
                        "drained",
                        "draining",
                        "fail",
                        "failing",
                        "maint",
                        "reserved",
                    ):
                        bucket["down"] += count
                if table:
                    sorted_parts = sorted(
                        table.items(),
                        key=lambda kv: kv[1]["total"],
                        reverse=True,
                    )[:4]
                    out["partitions"] = dict(sorted_parts)
        except Exception:
            pass

    return out
