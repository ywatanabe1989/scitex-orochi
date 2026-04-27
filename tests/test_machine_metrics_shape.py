"""Pin the orochi_machine-metrics wire shape for the Machines-tab display
(ywatanabe msg#16215).

Sidebar MACHINES + Machines-tab tooltip expect the producer to emit
an absolute used/total pair (not just percent) so the frontend can
render:

    CPU      — ``N cores`` (integer)
    RAM      — ``N/M GB``  (integers)
    Storage  — ``N/M TB``  (1 decimal)
    GPU      — ``N/M`` when present, ``n/a`` otherwise

mba + nas were showing empty fields because the Python producer
(scripts/client/_collect_agent_metadata/_metrics.py) only emitted
``disk_used_percent`` and no GPU info — the hub aggregator had no
"total" side for the N/M display. This test pins the required keys
so a future refactor cannot silently drop them again.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Agent package lives under scripts/client/ — add to sys.path so
# the test can import without pip-installing (same pattern as
# test_push_payload_sac_status.py).
_AGENT_META_DIR = Path(__file__).resolve().parents[1] / "scripts" / "client"
if str(_AGENT_META_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_META_DIR))

from _collect_agent_metadata._metrics import collect_machine_metrics  # noqa: E402

REQUIRED_KEYS = {
    # CPU shape: count + model string
    "cpu_count",
    "cpu_model",
    "load_avg_1m",
    "load_avg_5m",
    "load_avg_15m",
    # RAM shape: total + free + used + percent
    "mem_total_mb",
    "mem_free_mb",
    "mem_used_mb",
    "mem_used_percent",
    # Disk shape: total + used + percent (N/M TB needs total/used)
    "disk_total_mb",
    "disk_used_mb",
    "disk_used_percent",
    # GPU shape: list (possibly empty)
    "gpus",
}


def test_collect_machine_metrics_has_all_required_keys():
    """Pin the wire contract the hub aggregator reads."""
    m = collect_machine_metrics()
    missing = REQUIRED_KEYS - set(m.keys())
    assert not missing, f"missing keys in heartbeat metrics: {missing}"


def test_gpus_is_a_list():
    """``gpus`` must always be a list (possibly empty) — not None.

    The hub aggregator in ``hub/views/api/_resources.py`` iterates on
    ``gpus`` to project them into the per-orochi_machine resources dict; if
    this became ``None``, the aggregator would need a branch.
    """
    m = collect_machine_metrics()
    assert isinstance(m["gpus"], list)


def test_mem_used_mb_consistent_when_total_and_free_known():
    """``mem_used_mb`` should line up with ``total - free`` when both are set."""
    m = collect_machine_metrics()
    total = m.get("mem_total_mb")
    free = m.get("mem_free_mb")
    used = m.get("mem_used_mb")
    if total is None or free is None or used is None:
        # stdlib fallback couldn't read memory — not a test failure.
        return
    # Psutil "available" vs "free" semantics may drift by ~1 MB from
    # a naive subtraction; allow a small slack.
    assert abs(used - (total - free)) <= max(16, total // 1000), (
        f"mem_used_mb={used} inconsistent with total={total} - free={free}"
    )


def test_disk_total_and_used_populated_and_nonzero():
    """Both disk totals must be positive when the producer can read them.

    We don't pin the relationship between ``disk_used_mb`` and
    ``disk_used_percent`` because psutil (and macOS's df) compute
    percent as ``used / (used + free)`` to exclude reserved blocks,
    while ``disk_total_mb`` is the raw total — so naive division
    drifts. The frontend accepts this and renders both shapes.
    """
    m = collect_machine_metrics()
    total = m.get("disk_total_mb")
    used = m.get("disk_used_mb")
    pct = m.get("disk_used_percent")
    if not total or used is None or pct is None:
        return  # stdlib fallback couldn't read — skip, not fail
    assert total > 0
    assert used >= 0
    assert 0 <= pct <= 100
