#!/usr/bin/env bash
# hungry-signal.sh — Layer 2 coordinated dispatch: idle heads DM lead
# -----------------------------------------------------------------------------
# Problem statement (lead msg#16310)
#   Layer 1 (auto-dispatch-probe.sh, PR #320) forces idle heads to grab any
#   local-lane high-priority todo. That solves "idle = forbidden" but routes
#   blindly. Layer 2 adds a coordinated path: when a head has seen
#   subagent_count == 0 for N consecutive cycles, it DMs `lead` saying
#   "ready for dispatch" and lead picks a better-matched todo with context.
#
# Logic
#   * Query local `scitex-agent-container status head-<hostname> --terse
#     --json` (fallback to hub registry if sac is absent).
#   * If subagent_count == 0 this cycle AND the state file shows the same
#     reading N=HUNGRY_THRESHOLD cycles ago, compose and send a DM to lead:
#        channel = dm:agent:head-<host>|agent:lead       (sorted-pair canonical)
#        text    = "head-<host>: hungry — 0 subagents × <N> cycles, ready
#                   for dispatch. lane: <label>, alive: <list>"
#   * Once fired, write "fired" marker to state; skip further DMs until a
#     non-zero reading resets the counter. This is the spam guard.
#   * --dry-run logs "would-DM" without touching the hub or marker.
#   * --yes posts the DM and arms the fired marker.
#   * SCITEX_HUNGRY_DISABLED=1 silent no-op exit (kill switch).
#
# Cadence: 10 min (HUNGRY_CADENCE_SECONDS=600, launchd/systemd).
# Threshold: 2 cycles (HUNGRY_THRESHOLD=2) → DM fires at the 2nd consecutive
#            zero-reading, i.e. roughly 10–20 min of real idleness.
#
# This script shares idiom with auto-dispatch-probe.sh (PR #320): NDJSON to
# stdout, severity to stderr, log file under ~/Library/Logs/scitex (mac) or
# ~/.local/state/scitex (linux). State + log directories match.
#
# Exit codes
#   0  ok (or benign skip: disabled / no-token / non-head host)
#   1  advisory (DM already fired this stretch — state machine intact)
#   2  warn (hub/sac reachable but no subagent_count payload returned)
#   3  critical (can't parse machines yaml / write state file)
# -----------------------------------------------------------------------------

set -o pipefail
shopt -s nullglob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Repo root for in-tree invocation: scripts/client/hungry-signal.sh → ../..
# Stable-bin invocation honours $SCITEX_OROCHI_REPO_ROOT injected by the
# installer (same pattern as PR #326 todo#466).
if [ -n "${SCITEX_OROCHI_REPO_ROOT:-}" ] && [ -d "$SCITEX_OROCHI_REPO_ROOT" ]; then
  REPO_ROOT="$SCITEX_OROCHI_REPO_ROOT"
else
  REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi
MACHINES_YAML="${MACHINES_YAML:-$REPO_ROOT/orochi-machines.yaml}"

STATE_DIR="${HUNGRY_STATE_DIR:-$HOME/.local/state/scitex}"
STATE_FILE="${HUNGRY_STATE_FILE:-$STATE_DIR/hungry-signal.state}"

if [ "$(uname -s)" = "Darwin" ]; then
  LOG_DIR="${HUNGRY_LOG_DIR:-$HOME/Library/Logs/scitex}"
else
  LOG_DIR="${HUNGRY_LOG_DIR:-$HOME/.local/state/scitex}"
fi
LOG_FILE="$LOG_DIR/hungry-signal.log"

HUB_URL_DEFAULT="${SCITEX_OROCHI_HUB_URL:-https://scitex-orochi.com}"
HUB_URL="${HUB_URL_DEFAULT%/}"
CURL_TIMEOUT="${HUNGRY_CURL_TIMEOUT:-8}"
HUNGRY_THRESHOLD="${HUNGRY_THRESHOLD:-2}"

dry_run=1
only_host=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1; shift ;;
    --yes|-y)  dry_run=0; shift ;;
    --host)    only_host="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,45p' "$0"; exit 0 ;;
    *) printf 'unknown arg: %s\n' "$1" >&2; exit 64 ;;
  esac
done

mkdir -p "$LOG_DIR" "$STATE_DIR" 2>/dev/null || {
  printf 'hungry-signal: cannot create state/log dirs\n' >&2
  exit 3
}

TS_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
NOW_EPOCH="$(date -u +%s)"
LOCAL_HOST="$(hostname -s 2>/dev/null || hostname)"

log()    { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG_FILE"; }
stderr() { printf '%s\n' "$*" >&2; }

worst_exit=0
bump_exit() {
  local code="$1"
  if [ "$code" -gt "$worst_exit" ]; then
    worst_exit="$code"
  fi
}

# -----------------------------------------------------------------------------
# Kill switch — silent exit 0.
# -----------------------------------------------------------------------------
if [ "${SCITEX_HUNGRY_DISABLED:-0}" = "1" ]; then
  log "disabled via SCITEX_HUNGRY_DISABLED=1 — no-op"
  exit 0
fi

# -----------------------------------------------------------------------------
# Lane map — mirrors auto-dispatch-probe.sh for consistency. The DM payload
# only includes the lane label; lead-side handler does the todo lookup.
# -----------------------------------------------------------------------------
lane_for_host() {
  case "$1" in
    mba)            printf 'infrastructure' ;;
    ywata-note-win) printf 'specialized-wsl-access' ;;
    spartan)        printf 'specialized-domain' ;;
    nas)            printf 'hub-admin' ;;
    *)              printf '' ;;
  esac
}

# -----------------------------------------------------------------------------
# parse_machines_yaml — same shape as auto-dispatch-probe.sh. Returns a
# newline-separated list of head canonical names.
# -----------------------------------------------------------------------------
parse_machines_yaml() {
  if [ ! -f "$MACHINES_YAML" ]; then
    stderr "hungry-signal: machines yaml missing: $MACHINES_YAML"
    return 1
  fi
  python3 - "$MACHINES_YAML" <<'PY'
import sys
path = sys.argv[1]
try:
    import yaml
    with open(path) as f:
        doc = yaml.safe_load(f) or {}
    for m in (doc.get("machines") or []):
        name = (m.get("canonical_name") or "").strip()
        role = ((m.get("fleet_role") or {}).get("role") or "").strip()
        if name and role == "head":
            print(name)
except ImportError:
    import re
    with open(path) as f:
        text = f.read()
    for blk in re.split(r'^\s*-\s+canonical_name:\s*', text, flags=re.MULTILINE)[1:]:
        m = re.match(r'([A-Za-z0-9_.-]+)', blk)
        if not m:
            continue
        if re.search(r'role:\s*head\b', blk):
            print(m.group(1).strip())
PY
}

# -----------------------------------------------------------------------------
# resolve_self_host — canonical fleet label for the box we're on.
# -----------------------------------------------------------------------------
resolve_self_host() {
  if [ -n "${SCITEX_OROCHI_HOSTNAME:-}" ]; then
    printf '%s' "$SCITEX_OROCHI_HOSTNAME"
    return
  fi
  if [ -x "$SCRIPT_DIR/resolve-hostname" ]; then
    local out
    out="$("$SCRIPT_DIR/resolve-hostname" 2>/dev/null)"
    if [ -n "$out" ]; then
      printf '%s' "$out"
      return
    fi
  fi
  printf '%s' "$LOCAL_HOST"
}

# -----------------------------------------------------------------------------
# read_subagent_count — prefer `scitex-agent-container status --terse --json`
# when sac is on PATH (source of truth), fall back to the hub registry. The
# sac path is cheaper and works even when the hub is unreachable.
#
# Prints two lines:
#   <subagent_count>
#   <comma-sep alive agent names>   (for the DM context blob; may be "")
# Returns non-zero if neither source yields a reading.
# -----------------------------------------------------------------------------
read_subagent_count() {
  local host="$1"
  local agent_name="head-$host"
  local count="" alive=""

  # Source 1: local sac, if available. We ask for *all* agents on this box
  # (so the "alive" list can fill the DM context blob), then extract
  # head-<host>.subagent_count from the resulting payload.
  if command -v scitex-agent-container >/dev/null 2>&1; then
    local sac_json
    sac_json="$(scitex-agent-container status --terse --json 2>/dev/null || true)"
    if [ -n "$sac_json" ]; then
      read -r count alive < <(
        SAC_JSON="$sac_json" AGENT_NAME="$agent_name" python3 -c '
import json, os, sys
agent = os.environ["AGENT_NAME"]
try:
    data = json.loads(os.environ.get("SAC_JSON") or "{}")
except Exception:
    print("")
    print("")
    sys.exit(0)
# sac status --terse --json shapes seen in the wild: either a list of
# agent dicts, or a dict keyed by agent name, or a top-level dict with
# "agents": [...]. Handle all three.
agents = []
if isinstance(data, list):
    agents = data
elif isinstance(data, dict):
    if isinstance(data.get("agents"), list):
        agents = data["agents"]
    else:
        # dict keyed by agent name
        for k, v in data.items():
            if isinstance(v, dict):
                v = {**v, "name": v.get("name") or k}
                agents.append(v)
count = ""
alive_names = []
for a in agents:
    if not isinstance(a, dict):
        continue
    name = str(a.get("name") or a.get("agent_id") or "")
    if not name:
        continue
    status = str(a.get("status") or "")
    # "alive" by sac convention: online OR running (sac has its own label
    # set; tolerate common variants).
    if status in ("online", "running", "up", "active"):
        alive_names.append(name)
    if name == agent:
        c = a.get("subagent_count")
        if c is not None:
            try:
                count = str(int(c))
            except (TypeError, ValueError):
                pass
print(count or "")
print(",".join(alive_names))
'
      )
      if [ -n "$count" ]; then
        printf '%s\n%s\n' "$count" "$alive"
        return 0
      fi
    fi
  fi

  # Source 2: hub /api/agents/. Uses the same token resolution as
  # auto-dispatch-probe.sh.
  local token="${SCITEX_OROCHI_TOKEN:-}"
  if [ -z "$token" ]; then
    local token_src="$HOME/.dotfiles/src/.bash.d/secrets/010_scitex/01_orochi.src"
    if [ -r "$token_src" ]; then
      # shellcheck disable=SC1090
      . "$token_src" 2>/dev/null || true
      token="${SCITEX_OROCHI_TOKEN:-}"
    fi
  fi
  if [ -z "$token" ]; then
    log "skip: no SCITEX_OROCHI_TOKEN and sac unavailable"
    return 1
  fi
  if ! command -v curl >/dev/null 2>&1; then
    log "skip: curl not installed"
    return 1
  fi

  local endpoint="$HUB_URL/api/agents/?token=$token"
  local http_code body tmp
  tmp="$(mktemp -t hungry-signal.XXXXXX)"
  http_code="$(curl -sS -o "$tmp" -w '%{http_code}' \
      --max-time "$CURL_TIMEOUT" \
      -H 'Accept: application/json' \
      "$endpoint" 2>/dev/null || echo 000)"
  body="$(cat "$tmp" 2>/dev/null || true)"
  rm -f "$tmp" 2>/dev/null || true
  if [ "$http_code" != "200" ]; then
    log "hub error ($http_code) — cannot read subagent_count"
    return 1
  fi
  read -r count alive < <(
    AGENTS_JSON="$body" AGENT_NAME="$agent_name" python3 -c '
import json, os
agent = os.environ["AGENT_NAME"]
try:
    data = json.loads(os.environ.get("AGENTS_JSON") or "[]")
except Exception:
    data = []
if not isinstance(data, list):
    data = []
count = ""
alive_names = []
for a in data:
    if not isinstance(a, dict):
        continue
    name = str(a.get("name") or "")
    if not name:
        continue
    status = str(a.get("status") or "")
    if status == "online":
        alive_names.append(name)
    if name == agent:
        c = a.get("subagent_count")
        if c is not None:
            try:
                count = str(int(c))
            except (TypeError, ValueError):
                pass
print(count or "")
print(",".join(alive_names))
'
  )
  if [ -z "$count" ]; then
    return 1
  fi
  printf '%s\n%s\n' "$count" "$alive"
  return 0
}

# -----------------------------------------------------------------------------
# State file — one line per head, TAB-separated:
#   <host>\t<consecutive_zero_cycles>\t<fired_flag>\t<last_update_epoch>
#
# fired_flag is "1" after a DM is actually sent; cleared on the first
# non-zero reading that follows (spam guard — one DM per idle stretch).
# -----------------------------------------------------------------------------
state_get() {
  local host="$1"
  if [ ! -f "$STATE_FILE" ]; then
    printf '0\t0\t0\n'
    return
  fi
  awk -F'\t' -v h="$host" '$1==h { print $2 "\t" $3 "\t" $4; found=1 } END { if (!found) print "0\t0\t0" }' \
    "$STATE_FILE"
}

state_update() {
  local host="$1" cycles="$2" fired="$3" epoch="$4"
  local tmp
  tmp="$(mktemp -t hungry-signal-state.XXXXXX)"
  if [ -f "$STATE_FILE" ]; then
    awk -F'\t' -v h="$host" '$1 != h { print }' "$STATE_FILE" >"$tmp" 2>/dev/null || true
  fi
  printf '%s\t%s\t%s\t%s\n' "$host" "$cycles" "$fired" "$epoch" >>"$tmp"
  mv -f "$tmp" "$STATE_FILE"
}

# -----------------------------------------------------------------------------
# send_dm — POST /api/messages/ to the canonical agent↔agent DM channel.
# Canonical channel name: dm:agent:<A>|agent:<B> with names sorted so A↔B
# and B↔A collapse to a single channel (matches hub/static/hub/app/
# agent-actions.js:_openAgentDmSimple).
# -----------------------------------------------------------------------------
send_dm() {
  local sender="$1" recipient="$2" text="$3"
  local token="${SCITEX_OROCHI_TOKEN:-}"
  if [ -z "$token" ]; then
    local token_src="$HOME/.dotfiles/src/.bash.d/secrets/010_scitex/01_orochi.src"
    if [ -r "$token_src" ]; then
      # shellcheck disable=SC1090
      . "$token_src" 2>/dev/null || true
      token="${SCITEX_OROCHI_TOKEN:-}"
    fi
  fi
  if [ -z "$token" ]; then
    log "send_dm skip: no SCITEX_OROCHI_TOKEN"
    return 1
  fi
  if ! command -v curl >/dev/null 2>&1; then
    log "send_dm skip: curl missing"
    return 1
  fi

  # Canonical channel = sorted pair joined with "|".
  local channel
  channel="$(python3 -c '
import sys
a, b = sys.argv[1:3]
pair = sorted([a, b])
print("dm:agent:" + pair[0] + "|agent:" + pair[1])
' "$sender" "$recipient")"

  local endpoint="$HUB_URL/api/messages/?token=$token"
  local payload
  payload="$(python3 -c '
import json, sys
ch, snd, txt = sys.argv[1:4]
print(json.dumps({
    "channel": ch,
    "sender": snd,
    "payload": {"channel": ch, "content": txt},
}))
' "$channel" "$sender" "$text")"

  local http_code tmp
  tmp="$(mktemp -t hungry-signal-dm.XXXXXX)"
  http_code="$(curl -sS -o "$tmp" -w '%{http_code}' \
      --max-time "$CURL_TIMEOUT" \
      -X POST \
      -H 'Content-Type: application/json' \
      -H 'Accept: application/json' \
      --data "$payload" \
      "$endpoint" 2>/dev/null || echo 000)"
  local body
  body="$(cat "$tmp" 2>/dev/null || true)"
  rm -f "$tmp" 2>/dev/null || true

  case "$http_code" in
    200|201)
      log "DM sent: ${channel} http=${http_code}"
      return 0 ;;
    *)
      log "DM failed: http=${http_code} body=${body:0:200}"
      return 1 ;;
  esac
}

# -----------------------------------------------------------------------------
# emit_ndjson — one NDJSON line on stdout per run (one-head-per-host model).
# -----------------------------------------------------------------------------
emit_ndjson() {
  local host="$1" agent="$2" decision="$3" reason="$4"
  local subagent_count="$5" cycles="$6" fired="$7" lane="$8"
  python3 - "$TS_ISO" "$host" "$agent" "$decision" "$reason" \
                     "$subagent_count" "$cycles" "$fired" "$lane" \
                     "$dry_run" "$HUNGRY_THRESHOLD" <<'PY'
import json, sys
ts, host, agent, decision, reason, sc, cycles, fired, lane, dry, thresh = sys.argv[1:]
def _ival(x, d=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return d
obj = {
    "schema": "scitex-orochi/hungry-signal/v1",
    "ts": ts,
    "host": host,
    "agent": agent,
    "decision": decision,
    "reason": reason,
    "subagent_count": _ival(sc, -1),
    "consecutive_zero_cycles": _ival(cycles, 0),
    "fired": fired == "1",
    "threshold": _ival(thresh, 2),
    "lane": lane or "",
    "dry_run": dry == "1",
}
print(json.dumps(obj, separators=(",", ":"), sort_keys=False))
PY
}

# -----------------------------------------------------------------------------
# probe_head — per-host cycle. Contract: idempotent state machine.
#
#   subagent_count > 0  → cycles=0, fired=0 (reset everything)
#   subagent_count == 0
#     cycles+1 < threshold        → cycles++, fired unchanged, no DM
#     cycles+1 >= threshold
#       fired == 0                → DM lead, fired=1 (arm guard)
#       fired == 1                → skip (spam guard; already DM'd once)
# -----------------------------------------------------------------------------
probe_head() {
  local host="$1"
  local agent_name="head-$host"
  local lane; lane="$(lane_for_host "$host")"

  local two_lines count alive
  if ! two_lines="$(read_subagent_count "$host")"; then
    emit_ndjson "$host" "$agent_name" "skip" "no_subagent_count_source" \
      "-1" "0" "0" "$lane"
    bump_exit 2
    return
  fi
  count="$(printf '%s' "$two_lines" | awk 'NR==1')"
  alive="$(printf '%s' "$two_lines" | awk 'NR==2')"
  : "${count:=-1}"
  : "${alive:=}"

  local prior prior_cycles prior_fired
  prior="$(state_get "$host")"
  prior_cycles="$(printf '%s' "$prior" | awk -F'\t' '{print $1}')"
  prior_fired="$(printf '%s' "$prior" | awk -F'\t' '{print $2}')"
  : "${prior_cycles:=0}"
  : "${prior_fired:=0}"

  # Non-zero reading: reset counter + fired flag. Silent-success at exit 0.
  if [ "$count" -gt 0 ] 2>/dev/null; then
    if [ "$prior_cycles" != "0" ] || [ "$prior_fired" != "0" ]; then
      if [ "$dry_run" -eq 0 ]; then
        state_update "$host" 0 0 "$NOW_EPOCH"
      fi
    fi
    emit_ndjson "$host" "$agent_name" "noop" "subagent_count=${count}_reset" \
      "$count" "0" "0" "$lane"
    return
  fi

  if [ "$count" != "0" ]; then
    # Unknown / parse error.
    emit_ndjson "$host" "$agent_name" "skip" "subagent_count_unknown(${count})" \
      "$count" "$prior_cycles" "$prior_fired" "$lane"
    bump_exit 2
    return
  fi

  # count == 0
  local new_cycles=$((prior_cycles + 1))

  if [ "$new_cycles" -lt "$HUNGRY_THRESHOLD" ]; then
    # Still warming up — increment counter, don't DM yet.
    if [ "$dry_run" -eq 0 ]; then
      state_update "$host" "$new_cycles" "$prior_fired" "$NOW_EPOCH"
    fi
    emit_ndjson "$host" "$agent_name" "counting" \
      "zero_cycles=${new_cycles}/${HUNGRY_THRESHOLD}" \
      "$count" "$new_cycles" "$prior_fired" "$lane"
    return
  fi

  # Threshold met. Spam guard: already fired this stretch?
  if [ "$prior_fired" = "1" ]; then
    if [ "$dry_run" -eq 0 ]; then
      state_update "$host" "$new_cycles" 1 "$NOW_EPOCH"
    fi
    emit_ndjson "$host" "$agent_name" "skip" "already_fired_awaiting_reset" \
      "$count" "$new_cycles" "1" "$lane"
    bump_exit 1
    return
  fi

  # Fire.
  local text
  text="${agent_name}: hungry — 0 subagents × ${new_cycles} cycles, ready for dispatch. lane: ${lane:-none}, alive: ${alive:-none}"

  if [ "$dry_run" -eq 1 ]; then
    log "DRY-RUN would-DM lead: ${text}"
    emit_ndjson "$host" "$agent_name" "would_dm" "dry_run" \
      "$count" "$new_cycles" "$prior_fired" "$lane"
    return
  fi

  if send_dm "$agent_name" "lead" "$text"; then
    state_update "$host" "$new_cycles" 1 "$NOW_EPOCH"
    log "DM host=${host} cycles=${new_cycles} threshold=${HUNGRY_THRESHOLD} lane=${lane}"
    emit_ndjson "$host" "$agent_name" "dm_sent" "hungry_signal_posted" \
      "$count" "$new_cycles" "1" "$lane"
  else
    # Leave fired=0 so we can retry next tick — DM failures are transient.
    state_update "$host" "$new_cycles" 0 "$NOW_EPOCH"
    emit_ndjson "$host" "$agent_name" "dm_failed" "send_dm_nonzero" \
      "$count" "$new_cycles" "0" "$lane"
    bump_exit 1
  fi
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
  log "cycle start dry_run=${dry_run} only_host='${only_host}' threshold=${HUNGRY_THRESHOLD}"

  local heads
  if ! heads="$(parse_machines_yaml)"; then
    stderr "hungry-signal: failed to parse $MACHINES_YAML"
    return 3
  fi
  if [ -z "$heads" ]; then
    stderr "hungry-signal: no head-role machines in $MACHINES_YAML"
    return 3
  fi

  local self; self="$(resolve_self_host)"
  local target_host="${only_host:-$self}"

  if ! printf '%s\n' "$heads" | grep -qx "$target_host"; then
    log "target host '${target_host}' is not a head — exit 0"
    return 0
  fi

  probe_head "$target_host"

  log "cycle end worst_severity_code=${worst_exit}"
  return "$worst_exit"
}

main
