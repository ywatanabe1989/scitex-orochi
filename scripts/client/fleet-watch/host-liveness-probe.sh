#!/usr/bin/env bash
# host-liveness-probe.sh — fleet host-liveness probe with auto-revive (todo#271)
# -----------------------------------------------------------------------------
# Implementation lever for the 2026-04-20 incident: both ywata-note-win and
# spartan lost their tmux servers and nobody noticed for hours. This script
# runs on a 5-min launchd/cron schedule and:
#   1. Enumerates fleet hosts from orochi-machines.yaml
#   2. SSH-probes each host: tmux server reachable? expected agents alive?
#   3. Emits one NDJSON line per host on stdout (human-readable advisories on
#      stderr for launchd logs).
#   4. If --yes given: auto-revives missing agents by delegating to the
#      local healer (if alive) or running `scitex-agent-container start`
#      directly via SSH.
#
# Source-of-truth for expected agents: `expected_tmux_sessions:` key per
# host in orochi-machines.yaml at the repo root. If that key is missing or
# empty, the host is probed for tmux-server liveness only (no agent-set check).
#
# Usage:
#   ./scripts/client/fleet-watch/host-liveness-probe.sh              # dry-run (default)
#   ./scripts/client/fleet-watch/host-liveness-probe.sh --dry-run    # explicit
#   ./scripts/client/fleet-watch/host-liveness-probe.sh --yes        # actually revive
#   ./scripts/client/fleet-watch/host-liveness-probe.sh --host mba   # one host
#
# Exit codes (match disk-pressure-probe.sh convention):
#   0  ok        — every host's expected agents are alive
#   1  advisory  — unexpected agent found somewhere, or slurm advisory
#   2  warn      — expected agent missing on a host whose tmux server IS up
#   3  critical  — tmux server dead OR SSH unreachable on any host
#
# The process exit code is the WORST severity observed across all hosts.
# -----------------------------------------------------------------------------

# Deliberate choice to omit `set -u` — we rely on `${var:-default}`
# and explicit `+"${arr[@]}"` guards everywhere empty arrays are expanded.
set -o pipefail
shopt -s nullglob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
MACHINES_YAML="${MACHINES_YAML:-$REPO_ROOT/orochi-machines.yaml}"
LOG_DIR="${HOST_LIVENESS_LOG_DIR:-$HOME/.scitex/orochi/fleet-watch}"
LOG_FILE="$LOG_DIR/host-liveness-probe.log"
SSH_TIMEOUT="${SSH_TIMEOUT:-8}"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-5}"

# macOS has no `timeout` binary out of the box. Fall back to gtimeout
# (coreutils) or skip wrapping entirely — SSH's own ConnectTimeout +
# ServerAlive options catch most hangs. Resolve once at startup.
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_CMD=(timeout "$SSH_TIMEOUT")
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_CMD=(gtimeout "$SSH_TIMEOUT")
else
  TIMEOUT_CMD=()
fi

dry_run=1
only_host=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)   dry_run=1; shift ;;
    --yes|-y)    dry_run=0; shift ;;
    --host)      only_host="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,30p' "$0"; exit 0 ;;
    *) printf 'unknown arg: %s\n' "$1" >&2; exit 64 ;;
  esac
done

mkdir -p "$LOG_DIR"

TS_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LOCAL_HOST="$(hostname -s 2>/dev/null || hostname)"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG_FILE"
}

stderr() {
  printf '%s\n' "$*" >&2
}

# Worst severity observed across all hosts. Ordered so numeric max == worst.
#   0 ok  1 advisory  2 warn  3 critical
worst_exit=0

bump_exit() {
  local code="$1"
  if [ "$code" -gt "$worst_exit" ]; then
    worst_exit="$code"
  fi
}

# -----------------------------------------------------------------------------
# Parse orochi-machines.yaml
# Returns on stdout: one line per host, tab-separated, 3 columns:
#   <canonical_name>\t<expected_sessions_csv>\t<aliases_csv>
# Uses python3 + PyYAML. If PyYAML is missing, falls back to a minimal regex
# parser that extracts the three fields we need.
# -----------------------------------------------------------------------------
parse_machines_yaml() {
  if [ ! -f "$MACHINES_YAML" ]; then
    stderr "host-liveness-probe: machines yaml missing: $MACHINES_YAML"
    return 1
  fi
  python3 - "$MACHINES_YAML" <<'PY'
import sys, re
path = sys.argv[1]
try:
    import yaml
    with open(path) as f:
        doc = yaml.safe_load(f) or {}
    for m in (doc.get("machines") or []):
        name = (m.get("canonical_name") or "").strip()
        if not name:
            continue
        expected = [s for s in (m.get("expected_tmux_sessions") or []) if s]
        aliases = [a for a in (m.get("aliases") or []) if a]
        hostname = (m.get("hostname") or "").strip()
        if hostname and hostname not in aliases:
            aliases.append(hostname)
        print(f"{name}\t{','.join(expected)}\t{','.join(aliases)}")
except ImportError:
    # Minimal fallback: walk YAML looking for canonical_name +
    # expected_tmux_sessions + aliases + hostname blocks.
    with open(path) as f:
        text = f.read()
    blocks = re.split(r'^\s*-\s+canonical_name:\s*', text, flags=re.MULTILINE)
    def _collect_list(blk, key):
        m = re.search(
            rf'^\s*{key}:\s*\n((?:\s+-\s+[^\n]+\n)+)',
            blk, flags=re.MULTILINE,
        )
        out = []
        if m:
            for line in m.group(1).splitlines():
                m2 = re.match(r'\s*-\s+([A-Za-z0-9_.-]+)', line)
                if m2:
                    out.append(m2.group(1).strip())
        return out
    def _collect_scalar(blk, key):
        m = re.search(rf'^\s*{key}:\s*([A-Za-z0-9_.-]+)', blk, flags=re.MULTILINE)
        return m.group(1).strip() if m else ""
    for blk in blocks[1:]:
        mname = re.match(r'([A-Za-z0-9_.-]+)', blk)
        if not mname:
            continue
        name = mname.group(1).strip()
        sessions = _collect_list(blk, "expected_tmux_sessions")
        aliases = _collect_list(blk, "aliases")
        hostname = _collect_scalar(blk, "hostname")
        if hostname and hostname not in aliases:
            aliases.append(hostname)
        print(f"{name}\t{','.join(sessions)}\t{','.join(aliases)}")
PY
}

# -----------------------------------------------------------------------------
# Probe one host via SSH. Emits a JSON object on stdout (one NDJSON line).
# Bumps $worst_exit with the host's severity.
# When --yes given, attempts to revive missing agents.
# -----------------------------------------------------------------------------
probe_host() {
  local host="$1"
  local expected_csv="$2"
  local aliases_csv="${3:-}"

  local expected_arr=()
  if [ -n "$expected_csv" ]; then
    IFS=',' read -r -a expected_arr <<<"$expected_csv"
  fi
  local aliases_arr=()
  if [ -n "$aliases_csv" ]; then
    IFS=',' read -r -a aliases_arr <<<"$aliases_csv"
  fi

  local ssh_cmd=(ssh -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=3 -o ServerAliveCountMax=2)

  # Local-host short-circuit: don't SSH to ourselves. Priority:
  #   1. SCITEX_AGENT_LOCAL_HOSTS env (seeded by host_identity.py at boot)
  #   2. direct match $LOCAL_HOST == $host
  #   3. $LOCAL_HOST is in the yaml's aliases[] for this host
  local is_local=0
  case ",${SCITEX_AGENT_LOCAL_HOSTS:-}," in
    *",${host},"*) is_local=1 ;;
  esac
  if [ "$host" = "$LOCAL_HOST" ]; then
    is_local=1
  fi
  if [ "$is_local" -eq 0 ] && [ "${#aliases_arr[@]}" -gt 0 ]; then
    local a
    for a in "${aliases_arr[@]}"; do
      if [ "$a" = "$LOCAL_HOST" ] || [ "$a" = "$(hostname 2>/dev/null)" ]; then
        is_local=1
        break
      fi
    done
  fi

  local probe_script='
set -u
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
if command -v tmux >/dev/null 2>&1; then
  if tmux_out=$(tmux list-sessions -F "#{session_name}" 2>/dev/null); then
    echo "TMUX_OK"
    echo "$tmux_out"
  else
    echo "TMUX_DEAD"
  fi
else
  echo "TMUX_MISSING"
fi
'

  local remote_out="" rc=0
  if [ "$is_local" -eq 1 ]; then
    remote_out="$(bash -c "$probe_script" 2>/dev/null)"
    rc=$?
  else
    remote_out="$("${TIMEOUT_CMD[@]}" "${ssh_cmd[@]}" "$host" "bash -s" <<<"$probe_script" 2>/dev/null)"
    rc=$?
  fi

  # -----------------------------------------------------------------------
  # Classify severity.
  # -----------------------------------------------------------------------
  local severity="ok"
  local severity_code=0
  local reachable="true"
  local tmux_state="unknown"
  local alive_sessions=()
  local missing=()
  local unexpected=()
  local actions_taken=()

  if [ $rc -ne 0 ] || [ -z "$remote_out" ]; then
    reachable="false"
    tmux_state="ssh_unreachable"
    severity="critical"
    severity_code=3
  else
    # Parse the remote_out block
    local first_line
    first_line="$(printf '%s\n' "$remote_out" | head -n1)"
    case "$first_line" in
      TMUX_OK)
        tmux_state="running"
        # Remaining lines are session names
        while IFS= read -r name; do
          [ -z "$name" ] && continue
          alive_sessions+=("$name")
        done < <(printf '%s\n' "$remote_out" | tail -n +2)
        ;;
      TMUX_DEAD)
        tmux_state="dead"
        severity="critical"
        severity_code=3
        ;;
      TMUX_MISSING)
        tmux_state="tmux_not_installed"
        severity="critical"
        severity_code=3
        ;;
      *)
        tmux_state="unparseable"
        reachable="false"
        severity="critical"
        severity_code=3
        ;;
    esac
  fi

  # -----------------------------------------------------------------------
  # Cross-check against expected set (only when tmux is running and we have
  # an expected set).
  # -----------------------------------------------------------------------
  if [ "$tmux_state" = "running" ] && [ "${#expected_arr[@]}" -gt 0 ]; then
    for exp in "${expected_arr[@]}"; do
      local found=0
      for alive in "${alive_sessions[@]}"; do
        if [ "$exp" = "$alive" ]; then
          found=1; break
        fi
      done
      if [ $found -eq 0 ]; then
        missing+=("$exp")
      fi
    done
    for alive in "${alive_sessions[@]}"; do
      local declared=0
      for exp in "${expected_arr[@]}"; do
        if [ "$exp" = "$alive" ]; then
          declared=1; break
        fi
      done
      if [ $declared -eq 0 ]; then
        unexpected+=("$alive")
      fi
    done

    if [ "${#missing[@]}" -gt 0 ]; then
      # Missing expected agent — worse than advisory but tmux server is up,
      # so "warn" not "critical".
      if [ $severity_code -lt 2 ]; then
        severity="warn"; severity_code=2
      fi
    fi
    if [ "${#unexpected[@]}" -gt 0 ] && [ $severity_code -lt 1 ]; then
      severity="advisory"; severity_code=1
    fi
  fi

  # -----------------------------------------------------------------------
  # Auto-revive policy: only for `missing` agents on a host whose tmux is up.
  # (If tmux server is dead that's a critical — humans must handle that, the
  # revive path assumes a living tmux to attach into.)
  # -----------------------------------------------------------------------
  local revive_path="none"
  if [ "$tmux_state" = "running" ] && [ "${#missing[@]}" -gt 0 ]; then
    # Pick revive path. healer-<host> is in expected_arr AND alive_sessions?
    local healer_name="healer-${host}"
    # Also tolerate the legacy naming: mamba-healer-<host>
    local mamba_healer_name="mamba-healer-${host}"
    local healer_alive=0
    for a in "${alive_sessions[@]}"; do
      if [ "$a" = "$healer_name" ] || [ "$a" = "$mamba_healer_name" ]; then
        healer_alive=1; break
      fi
    done

    if [ $healer_alive -eq 1 ]; then
      revive_path="healer_delegate"
    else
      revive_path="ssh_direct"
    fi

    for m in "${missing[@]}"; do
      if [ $dry_run -eq 1 ]; then
        actions_taken+=("would_revive:${m}:via=${revive_path}")
      else
        if revive_agent "$host" "$m" "$revive_path" "$is_local"; then
          actions_taken+=("revived:${m}:via=${revive_path}")
        else
          actions_taken+=("revive_failed:${m}:via=${revive_path}")
        fi
      fi
    done
  fi

  bump_exit "$severity_code"

  # -----------------------------------------------------------------------
  # Emit NDJSON (stdout) + human advisory (stderr).
  # -----------------------------------------------------------------------
  local expected_csv_out alive_csv_out missing_csv_out unexpected_csv_out actions_csv_out
  expected_csv_out="$(csv_from_array "${expected_arr[@]+"${expected_arr[@]}"}")"
  alive_csv_out="$(csv_from_array "${alive_sessions[@]+"${alive_sessions[@]}"}")"
  missing_csv_out="$(csv_from_array "${missing[@]+"${missing[@]}"}")"
  unexpected_csv_out="$(csv_from_array "${unexpected[@]+"${unexpected[@]}"}")"
  actions_csv_out="$(csv_from_array "${actions_taken[@]+"${actions_taken[@]}"}")"

  emit_ndjson_line \
    "$host" "$severity" "$reachable" "$tmux_state" \
    "$expected_csv_out" \
    "$alive_csv_out" \
    "$missing_csv_out" \
    "$unexpected_csv_out" \
    "$revive_path" \
    "$actions_csv_out"

  if [ "$severity" != "ok" ]; then
    stderr "host-liveness-probe ${severity} on ${host}: tmux=${tmux_state} missing=[${missing_csv_out}] unexpected=[${unexpected_csv_out}] actions=[${actions_csv_out}]"
  fi
}

# Safe CSV join. Caller expands the array explicitly with the `+` pattern to
# tolerate empty arrays under nounset. Here we just join with comma.
csv_from_array() {
  local IFS=','
  printf '%s' "$*"
}

# Emit one NDJSON line. We construct by hand (no jq dep) but we JSON-escape
# strings via python3 for safety.
emit_ndjson_line() {
  local host="$1" severity="$2" reachable="$3" tmux_state="$4"
  local expected_csv="$5" alive_csv="$6" missing_csv="$7" unexpected_csv="$8"
  local revive_path="$9" actions_csv="${10}"
  python3 - "$TS_ISO" "$host" "$severity" "$reachable" "$tmux_state" \
                     "$expected_csv" "$alive_csv" "$missing_csv" "$unexpected_csv" \
                     "$revive_path" "$actions_csv" <<'PY'
import json, sys
ts, host, severity, reachable, tmux_state, exp, alive, missing, unexpected, revive_path, actions = sys.argv[1:]
def csv_to_list(s):
    return [x for x in s.split(",") if x]
obj = {
    "schema": "scitex-orochi/host-liveness-probe/v1",
    "ts": ts,
    "host": host,
    "severity": severity,
    "reachable": reachable == "true",
    "tmux_state": tmux_state,
    "expected_agents": csv_to_list(exp),
    "alive_agents": csv_to_list(alive),
    "missing": csv_to_list(missing),
    "unexpected": csv_to_list(unexpected),
    "revive_path": revive_path,
    "actions_taken": csv_to_list(actions),
}
print(json.dumps(obj, separators=(",", ":"), sort_keys=False))
PY
}

# -----------------------------------------------------------------------------
# Revive a missing agent. Returns 0 on success, non-zero on failure.
#
# Path 1 (healer_delegate): ssh <host> and append a one-line instruction to
#   the healer's inbox file (`~/.scitex/orochi/healer-<host>/inbox`). This
#   keeps the revive decision observable by the healer — the healer then
#   runs the actual `scitex-agent-container start` call in its own context.
#   If the inbox dir doesn't exist we fall through to direct ssh.
#
# Path 2 (ssh_direct): ssh <host> 'scitex-agent-container start <agent>'.
#   Used when no healer is alive on the host.
#
# Both paths are guarded by $dry_run at the caller; this function only runs
# when dry_run=0.
# -----------------------------------------------------------------------------
revive_agent() {
  local host="$1" agent="$2" path="$3" is_local="$4"

  case "$path" in
    healer_delegate)
      local inbox_dir="\$HOME/.scitex/orochi/healer-${host}"
      local line="revive ${agent} at $(date -u +%Y-%m-%dT%H:%M:%SZ) by host-liveness-probe@${LOCAL_HOST}"
      # Subshell that verifies the inbox dir exists; if not, caller falls through.
      local cmd="if [ -d ${inbox_dir} ]; then printf '%s\\n' '${line}' >> ${inbox_dir}/inbox; echo INBOX_OK; else echo NO_INBOX; fi"
      local out
      if [ "$is_local" -eq 1 ]; then
        out="$(bash -lc "$cmd" 2>&1)"
      else
        out="$("${TIMEOUT_CMD[@]}" ssh -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" -o BatchMode=yes -o ServerAliveInterval=3 -o ServerAliveCountMax=2 "$host" "$cmd" 2>&1)"
      fi
      if printf '%s' "$out" | grep -q INBOX_OK; then
        log "revive ${host}/${agent} via healer inbox ok"
        return 0
      fi
      log "revive ${host}/${agent}: healer inbox absent, falling back to ssh_direct"
      ;;
  esac

  # ssh_direct (or healer_delegate fallthrough)
  local cmd="scitex-agent-container start ${agent} 2>&1 || sac start ${agent} 2>&1"
  if [ "$is_local" -eq 1 ]; then
    if bash -lc "$cmd" >>"$LOG_FILE" 2>&1; then
      log "revive ${host}/${agent} via ssh_direct ok"
      return 0
    fi
  else
    if "${TIMEOUT_CMD[@]}" ssh -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" -o BatchMode=yes -o ServerAliveInterval=3 -o ServerAliveCountMax=2 "$host" "$cmd" >>"$LOG_FILE" 2>&1; then
      log "revive ${host}/${agent} via ssh_direct ok"
      return 0
    fi
  fi
  log "revive ${host}/${agent} FAILED"
  return 1
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
  log "cycle start dry_run=${dry_run} only_host='${only_host}'"
  local hosts_data
  if ! hosts_data="$(parse_machines_yaml)"; then
    stderr "host-liveness-probe: failed to parse $MACHINES_YAML"
    return 3
  fi
  if [ -z "$hosts_data" ]; then
    stderr "host-liveness-probe: no hosts in $MACHINES_YAML"
    return 3
  fi

  while IFS=$'\t' read -r host expected_csv aliases_csv; do
    [ -z "$host" ] && continue
    if [ -n "$only_host" ] && [ "$host" != "$only_host" ]; then
      continue
    fi
    probe_host "$host" "$expected_csv" "${aliases_csv:-}"
  done <<<"$hosts_data"

  log "cycle end worst_severity_code=${worst_exit}"
  return "$worst_exit"
}

main
