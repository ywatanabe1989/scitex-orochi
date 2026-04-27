"""Integration test for scripts/client/hungry-signal.sh state-machine.

Drives the real bash probe in --dry-run mode against a stubbed
``scitex-agent-container`` binary so we can assert:

* The consecutive-zero counter increments on each zero reading.
* A non-zero reading resets counter + fired flag.
* The DM fires once when the threshold is met and then the fired flag
  is set (spam guard).
* --dry-run never writes to the state file (so real runs aren't masked
  by observation-mode ticks).

We inject a stub sac via PATH so the probe calls our fake instead of
the real binary. PATH=<tmpdir>:... puts our fake first.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "scripts" / "client" / "hungry-signal.sh"
MACHINES_YAML_FIXTURE = textwrap.dedent(
    """\
    machines:
      - canonical_name: mba
        fleet_role:
          role: head
      - canonical_name: nas
        fleet_role:
          role: head
    """
)


def _write_stub_sac(tmpdir: Path, orochi_subagent_count: int) -> Path:
    """Write a stub scitex-agent-container that returns the desired count."""
    bin_dir = tmpdir / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "scitex-agent-container"
    payload = [
        {
            "name": "head-mba",
            "status": "online",
            "orochi_subagent_count": orochi_subagent_count,
        }
    ]
    # The stub must be robust to flag ordering — sac is called as
    # "scitex-agent-container status --terse --json" so we just echo a
    # fixed JSON doc regardless of argv.
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f"echo {json.dumps(json.dumps(payload))}\n"
    )
    stub.chmod(0o755)
    return bin_dir


def _invoke(
    tmpdir: Path,
    orochi_subagent_count: int,
    *,
    dry_run: bool = True,
    threshold: int = 2,
    state_dir: Path | None = None,
) -> dict:
    state_dir = state_dir or (tmpdir / "state")
    state_dir.mkdir(exist_ok=True)
    log_dir = tmpdir / "log"
    log_dir.mkdir(exist_ok=True)
    machines_yaml = tmpdir / "orochi-machines.yaml"
    machines_yaml.write_text(MACHINES_YAML_FIXTURE)

    stub_bindir = _write_stub_sac(tmpdir, orochi_subagent_count)
    env = {
        **os.environ,
        "PATH": f"{stub_bindir}:{os.environ.get('PATH', '')}",
        "MACHINES_YAML": str(machines_yaml),
        "HUNGRY_STATE_DIR": str(state_dir),
        "HUNGRY_STATE_FILE": str(state_dir / "hungry-signal.state"),
        "HUNGRY_LOG_DIR": str(log_dir),
        "HUNGRY_THRESHOLD": str(threshold),
        # Force self-host to 'mba' so the probe targets our stub regardless
        # of the box the test runs on.
        "SCITEX_OROCHI_HOSTNAME": "mba",
        # Make sure we don't accidentally hit the network in --dry-run.
        "SCITEX_OROCHI_TOKEN": "",
    }
    args = ["bash", str(PROBE)]
    if dry_run:
        args.append("--dry-run")
    else:
        args.append("--yes")
    proc = subprocess.run(
        args, capture_output=True, text=True, env=env, timeout=30
    )
    stdout = proc.stdout.strip()
    # Parse the last NDJSON line emitted.
    lines = [ln for ln in stdout.splitlines() if ln.startswith("{")]
    assert lines, f"probe emitted no NDJSON: rc={proc.returncode} out={stdout!r} err={proc.stderr!r}"
    return json.loads(lines[-1])


def _read_state(state_dir: Path) -> dict | None:
    f = state_dir / "hungry-signal.state"
    if not f.exists():
        return None
    line = f.read_text().strip()
    if not line:
        return None
    # <host>\t<cycles>\t<fired>\t<epoch>
    parts = line.split("\t")
    if len(parts) < 4:
        return None
    return {"host": parts[0], "cycles": int(parts[1]), "fired": int(parts[2])}


# -----------------------------------------------------------------------------
# Counter semantics — the heart of the spam guard.
# -----------------------------------------------------------------------------


def test_dry_run_never_writes_state_file(tmp_path):
    """dry-run must not touch the state file — real runs would be masked."""
    state_dir = tmp_path / "state"
    result = _invoke(tmp_path, orochi_subagent_count=0, dry_run=True, threshold=2, state_dir=state_dir)
    assert result["decision"] in {"counting", "would_dm"}
    assert _read_state(state_dir) is None


def test_counter_increments_on_repeated_zero(tmp_path):
    """Two --yes ticks at orochi_subagent_count=0 → counter reaches threshold."""
    state_dir = tmp_path / "state"

    # Tick 1: first zero. cycles=1, below threshold=2 → "counting".
    r1 = _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=2, state_dir=state_dir)
    assert r1["decision"] == "counting"
    assert r1["consecutive_zero_cycles"] == 1
    assert r1["fired"] is False
    s1 = _read_state(state_dir)
    assert s1 is not None
    assert s1["cycles"] == 1
    assert s1["fired"] == 0

    # Tick 2: second zero. cycles=2, hits threshold. Would DM lead, but the
    # hub call will fail (no token) so decision=dm_failed. Either way, the
    # state file must record cycles=2 (fired depends on outcome).
    r2 = _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=2, state_dir=state_dir)
    assert r2["decision"] in {"dm_sent", "dm_failed"}
    assert r2["consecutive_zero_cycles"] == 2
    s2 = _read_state(state_dir)
    assert s2 is not None
    assert s2["cycles"] == 2


def test_non_zero_reading_resets_counter(tmp_path):
    """A healthy tick wipes cycles + fired flag so the next idle stretch starts fresh."""
    state_dir = tmp_path / "state"

    # Start with a zero to plant cycles=1.
    _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=2, state_dir=state_dir)
    assert _read_state(state_dir)["cycles"] == 1

    # Non-zero reading resets to 0/0.
    r = _invoke(tmp_path, orochi_subagent_count=2, dry_run=False, threshold=2, state_dir=state_dir)
    assert r["decision"] == "noop"
    assert r["consecutive_zero_cycles"] == 0
    s = _read_state(state_dir)
    assert s["cycles"] == 0
    assert s["fired"] == 0


def test_already_fired_flag_suppresses_duplicate_dm(tmp_path):
    """Once fired=1 is armed, further zero ticks must not re-fire."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    # Seed state: cycles=5, fired=1 (as if we DM'd 3 cycles ago and heard nothing).
    (state_dir / "hungry-signal.state").write_text("mba\t5\t1\t0\n")

    r = _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=2, state_dir=state_dir)
    assert r["decision"] == "skip"
    assert r["reason"] == "already_fired_awaiting_reset"
    assert r["fired"] is True
    # cycles continues to increment so we can see how long the idle stretch
    # has been going (visibility), but no DM.
    assert r["consecutive_zero_cycles"] == 6


def test_non_zero_clears_prior_fired_flag(tmp_path):
    """Once the head is busy again, the spam-guard flag releases."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "hungry-signal.state").write_text("mba\t5\t1\t0\n")

    _invoke(tmp_path, orochi_subagent_count=1, dry_run=False, threshold=2, state_dir=state_dir)
    s = _read_state(state_dir)
    assert s["cycles"] == 0
    assert s["fired"] == 0


# -----------------------------------------------------------------------------
# Lifecycle coverage (msg#16389 / msg#16390) — the hungry-signal counter must
# track a realistic spawn → partial-completion → completion → reset sequence
# end-to-end. The parser + hub-registry round-trips that produce the counts
# are covered by ``tests/test_orochi_subagent_count_lifecycle.py`` +
# ``hub/tests/consumers/test_orochi_subagent_count_roundtrip.py``; this section
# exercises the bash state-machine's response to the full sequence.
# -----------------------------------------------------------------------------


def test_full_lifecycle_spawn_drain_idle_dm(tmp_path):
    """End-to-end sequence: idle → spawn batch → drain → idle → DM.

    The head starts idle (0), spawns 3 orochi_subagents (1 → 3), one finishes
    (→ 2), all finish (→ 0), then two further idle ticks trigger the DM.
    Pins the correctness contract: transient non-zero readings during a
    real batch must reset the counter each time, so the DM only fires
    after a *sustained* idle stretch past threshold.
    """
    state_dir = tmp_path / "state"

    # Tick A — idle cold start. cycles=1.
    r = _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=3, state_dir=state_dir)
    assert r["decision"] == "counting"
    assert _read_state(state_dir)["cycles"] == 1

    # Tick B — subagent spawned (1 local agent running). Counter resets.
    r = _invoke(tmp_path, orochi_subagent_count=1, dry_run=False, threshold=3, state_dir=state_dir)
    assert r["decision"] == "noop"
    assert _read_state(state_dir)["cycles"] == 0

    # Tick C — batch ramped to 3. Still busy, counter stays at 0.
    r = _invoke(tmp_path, orochi_subagent_count=3, dry_run=False, threshold=3, state_dir=state_dir)
    assert r["decision"] == "noop"
    assert _read_state(state_dir)["cycles"] == 0

    # Tick D — partial completion (2 still running). Still non-zero.
    r = _invoke(tmp_path, orochi_subagent_count=2, dry_run=False, threshold=3, state_dir=state_dir)
    assert r["decision"] == "noop"
    assert _read_state(state_dir)["cycles"] == 0

    # Tick E — full completion. First idle tick after batch. cycles=1.
    r = _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=3, state_dir=state_dir)
    assert r["decision"] == "counting"
    assert _read_state(state_dir)["cycles"] == 1

    # Tick F — still idle. cycles=2, below threshold=3.
    r = _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=3, state_dir=state_dir)
    assert r["decision"] == "counting"
    assert _read_state(state_dir)["cycles"] == 2

    # Tick G — still idle. cycles=3 hits threshold → DM attempt.
    r = _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=3, state_dir=state_dir)
    assert r["decision"] in {"dm_sent", "dm_failed"}
    assert _read_state(state_dir)["cycles"] == 3


def test_transient_spawn_resets_counter_mid_stretch(tmp_path):
    """A single non-zero tick mid-idle-stretch must reset the counter.

    Guards against a subtle regression: if the state machine kept
    incrementing through a brief busy interval (e.g. decremented rather
    than reset), the DM would fire spuriously seconds after the head
    finished a legitimate task.
    """
    state_dir = tmp_path / "state"

    # Two idle ticks — we're one tick shy of firing at threshold=3.
    _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=3, state_dir=state_dir)
    _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=3, state_dir=state_dir)
    assert _read_state(state_dir)["cycles"] == 2

    # Brief busy tick — one Agent spawned + finished between ticks.
    # Counter must reset to 0, NOT decrement by 1.
    r = _invoke(tmp_path, orochi_subagent_count=1, dry_run=False, threshold=3, state_dir=state_dir)
    assert r["decision"] == "noop"
    assert _read_state(state_dir)["cycles"] == 0

    # Back to idle. Must start over at 1 — NOT pick up where we left off.
    r = _invoke(tmp_path, orochi_subagent_count=0, dry_run=False, threshold=3, state_dir=state_dir)
    assert r["decision"] == "counting"
    assert _read_state(state_dir)["cycles"] == 1
