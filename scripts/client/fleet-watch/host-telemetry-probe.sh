#!/usr/bin/env bash
# host-telemetry-probe.sh — stock-CLI host instability probe
# -----------------------------------------------------------------------------
# Authored by head-nas 2026-04-14 as part of the ywatanabe msg#11554
# investigation into NAS instability. Originally targeted at NAS but
# host-agnostic by design so head-mba and other heads can mirror it.
#
# Principle (same as orochi_slurm-resource-scraper-contract.md): emit verbatim stock
# CLI output as the canonical wire format, wrapped in a minimal NDJSON
# envelope. No bespoke schema. No tool transforms the data.
#
# Side effects: none. Read-only queries only. No sudo. No Claude quota.
#
# Output: one NDJSON line per probe per invocation, appended to
#   ${OUT_DIR:-$HOME/.scitex/orochi/host-telemetry}/host-telemetry-$(orochi_hostname -s).ndjson
# -----------------------------------------------------------------------------

set -u
set -o pipefail

HOST="$(orochi_hostname -s 2>/dev/null || orochi_hostname)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
OUT_DIR="${HOST_TELEMETRY_OUT_DIR:-$HOME/.scitex/orochi/host-telemetry}"
OUT_FILE="$OUT_DIR/host-telemetry-${HOST}.ndjson"
mkdir -p "$OUT_DIR"

# JSON-safe string escaper for verbatim stdout.
# Handles: backslash, double-quote, control chars, newlines, tabs, CR.
json_escape() {
  python3 -c 'import json, sys; sys.stdout.write(json.dumps(sys.stdin.read()))'
}

emit() {
  # emit <cmd_kind> <cmd_string> <exit_code> <stdout>
  local kind="$1" cmd="$2" exit_code="$3" stdout="$4"
  local stdout_json
  stdout_json="$(printf '%s' "$stdout" | json_escape)"
  local cmd_json
  cmd_json="$(printf '%s' "$cmd" | json_escape)"
  printf '{"schema":"scitex-orochi/host-telemetry-probe/v1","host":"%s","ts":"%s","cmd_kind":"%s","cmd":%s,"exit_code":%d,"stdout":%s}\n' \
    "$HOST" "$TS" "$kind" "$cmd_json" "$exit_code" "$stdout_json" >> "$OUT_FILE"
}

run_and_emit() {
  # run_and_emit <cmd_kind> <cmd...>
  local kind="$1"; shift
  local cmd_string="$*"
  local out
  out="$("$@" 2>&1)"
  local rc=$?
  emit "$kind" "$cmd_string" "$rc" "$out"
}

# -----------------------------------------------------------------------------
# 1. Kernel-level pressure + load (universal, every OS w/ systemd + cgroupv2)
# -----------------------------------------------------------------------------
run_and_emit "proc_loadavg"    cat /proc/loadavg
run_and_emit "proc_meminfo"    grep -E '^(MemTotal|MemAvailable|MemFree|Buffers|Cached|SwapTotal|SwapFree|Dirty|Writeback):' /proc/meminfo
run_and_emit "proc_stat_cpu"   grep '^cpu ' /proc/stat
run_and_emit "proc_pressure_cpu" cat /proc/pressure/cpu
run_and_emit "proc_pressure_io"  cat /proc/pressure/io
run_and_emit "proc_pressure_memory" cat /proc/pressure/memory

# -----------------------------------------------------------------------------
# 2. cgroupv2 user slice accounting (the smoking-gun data on NAS)
# -----------------------------------------------------------------------------
if [ -d /sys/fs/cgroup/user.slice ]; then
  run_and_emit "cgroup_user_cpu_pressure"    cat /sys/fs/cgroup/user.slice/cpu.pressure
  run_and_emit "cgroup_user_memory_current"  cat /sys/fs/cgroup/user.slice/memory.current
  run_and_emit "cgroup_user_memory_peak"     cat /sys/fs/cgroup/user.slice/memory.peak
  run_and_emit "cgroup_user_memory_pressure" cat /sys/fs/cgroup/user.slice/memory.pressure
  run_and_emit "cgroup_user_io_pressure"     cat /sys/fs/cgroup/user.slice/io.pressure
  run_and_emit "cgroup_user_cpu_stat"        cat /sys/fs/cgroup/user.slice/cpu.stat
fi

# -----------------------------------------------------------------------------
# 3. SLURM (optional — no-op on hosts without SLURM, e.g. MBA)
# -----------------------------------------------------------------------------
if command -v squeue >/dev/null 2>&1; then
  run_and_emit "sinfo"                 sinfo -o '%P %D %T %N %C %m %G'
  run_and_emit "squeue"                squeue -h -o '%i|%P|%j|%u|%T|%M|%L|%D|%C|%m|%R'
  run_and_emit "scontrol_node_json"    scontrol show node --json
fi

# -----------------------------------------------------------------------------
# 4. Docker container stats (non-sudo-able on NAS, maybe-yes on MBA)
# -----------------------------------------------------------------------------
if command -v docker >/dev/null 2>&1 && docker ps >/dev/null 2>&1; then
  run_and_emit "docker_stats"          docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}|{{.PIDs}}'
  run_and_emit "docker_ps"             docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}'
fi

# -----------------------------------------------------------------------------
# 5. cloudflared tunnel health (flap rate signal — NAS-relevant)
# -----------------------------------------------------------------------------
# Count ERR lines from cloudflared user units in last 300s.
if command -v journalctl >/dev/null 2>&1; then
  for unit in cloudflared-bastion-nas cloudflared-bastion; do
    if systemctl --user is-enabled "$unit" >/dev/null 2>&1 || \
       systemctl --user is-active  "$unit" >/dev/null 2>&1; then
      run_and_emit "journalctl_${unit//-/_}_err_tail_300s" \
        bash -c "journalctl --user -u ${unit} --since '5 min ago' --no-pager 2>/dev/null | grep -cE ' ERR |error='"
    fi
  done
fi

# -----------------------------------------------------------------------------
# 6. systemd --user unit state (catch any flap at the unit level)
# -----------------------------------------------------------------------------
if command -v systemctl >/dev/null 2>&1; then
  run_and_emit "systemd_user_units_failed" \
    bash -c "systemctl --user list-units --state=failed --no-pager --no-legend 2>/dev/null | awk '{print \$1}'"
  run_and_emit "systemd_user_timers" \
    bash -c "systemctl --user list-timers --all --no-pager --no-legend 2>/dev/null"
fi

# -----------------------------------------------------------------------------
# 7. systemd-cgtop snapshot (one pass, non-interactive, CPU-ordered)
# -----------------------------------------------------------------------------
if command -v systemd-cgtop >/dev/null 2>&1; then
  run_and_emit "systemd_cgtop_snapshot" \
    bash -c "systemd-cgtop -b -n 1 --raw --order=cpu 2>/dev/null | head -30"
fi

exit 0
