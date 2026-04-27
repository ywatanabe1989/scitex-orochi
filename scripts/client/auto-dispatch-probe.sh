#!/usr/bin/env bash
# auto-dispatch-probe.sh — auto-dispatch daemon: "idle = forbidden" enforced by code
# -----------------------------------------------------------------------------
# >>> DEPRECATED (msg#16388 / ywatanabe msg#16380) <<<
#
# Layer 1 auto-dispatch moved from this per-host client probe to a
# server-side hook in the hub. On every heartbeat the hub now:
#   * maintains an idle-streak counter per head in its in-memory registry
#   * after N consecutive zero-subagent-count readings (default 2), DMs
#     the head with an auto-dispatch instruction that Claude parses
#   * enforces a 15-min per-head cooldown
#
# See ``hub/auto_dispatch.py`` + the ``check_agent_auto_dispatch`` hook
# in ``hub/registry/_heartbeat.py::update_heartbeat``.
#
# This script is kept in-tree so hosts where the server-side mechanism
# is unavailable (stale hub, local dev, emergency manual dispatch) can
# still run the probe. A follow-up PR may delete it after burn-in. To
# explicitly run it in the interim, pass ``--yes`` — the installer
# warns you not to enable the scheduler alongside server-side dispatch.
#
# To migrate: ``./scripts/client/install-auto-dispatch-probe.sh --uninstall``
# once your hub is on a orochi_version carrying the server-side hook.
# -----------------------------------------------------------------------------
# Problem statement (lead msg#15975, ywatanabe msg#15971)
#   Rules-based discipline failed. The fleet keeps dropping to
#   ``orochi_subagent_count == 0`` on individual heads (2026-04-20: head-mba hit 0
#   after the PR #315 revert). Replace rules with an automated probe+dispatch
#   loop that runs every 5 minutes and, for each head:
#     * queries the hub for this host's head-<orochi_hostname> registry payload
#     * if orochi_subagent_count == 0 AND agent is online AND no recent dispatch
#       has been injected (cooldown), picks the next high-priority TODO
#       matching this head's lane
#     * skips any TODO already claimed by a running subagent on any head
#       (best-effort via open-PR title/body cross-reference)
#     * injects a dispatch prompt into the head's tmux pane:
#           tmux send-keys -t head-<orochi_hostname>:0 '<prompt>' Enter
#
# Shape follows scripts/client/fleet-watch/host-liveness-probe.sh — NDJSON to
# stdout, severity advisories to stderr, log file under
# ~/Library/Logs/scitex (mac) or ~/.local/state/scitex (linux).
#
# Guardrails
#   * --dry-run      logs "would-dispatch" but does not tmux send-keys
#                    (default)
#   * --yes          actually dispatch
#   * --host <name>  constrain to one head only (debug)
#   * cooldown       15 min per head (state file)
#   * orochi_subagent_count upper bound 3 (lead's cap)
#   * skip injection when pane state classifier reports "busy"
#   * kill switch    SCITEX_AUTO_DISPATCH_DISABLED=1 — exits 0 silently
#   * gh unauth / hub 4xx — log + exit 0 (do not crash the scheduler)
#
# Exit codes
#   0  ok (or benign skip: disabled / unauth / hub-4xx / cooldown)
#   1  advisory (one or more heads skipped — busy, capped, already-claimed)
#   2  warn (hub reachable but no head payload returned)
#   3  critical (can't parse machines yaml / write state file)
# -----------------------------------------------------------------------------

set -o pipefail
shopt -s nullglob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Two-level climb: scripts/client/auto-dispatch-probe.sh → repo root
# (same shape as install-auto-dispatch-probe.sh / PR #297 fix).
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MACHINES_YAML="${MACHINES_YAML:-$REPO_ROOT/orochi-machines.yaml}"
STATE_DIR="${AUTO_DISPATCH_STATE_DIR:-$HOME/.local/state/scitex}"
STATE_FILE="${AUTO_DISPATCH_STATE_FILE:-$STATE_DIR/auto-dispatch.state}"

# Log dir: mac has Library/Logs, linux uses .local/state.
if [ "$(uname -s)" = "Darwin" ]; then
  LOG_DIR="${AUTO_DISPATCH_LOG_DIR:-$HOME/Library/Logs/scitex}"
else
  LOG_DIR="${AUTO_DISPATCH_LOG_DIR:-$HOME/.local/state/scitex}"
fi
LOG_FILE="$LOG_DIR/auto-dispatch.log"

PICK_HELPER="${AUTO_DISPATCH_PICK_HELPER:-$SCRIPT_DIR/auto-dispatch-pick-todo.py}"
HUB_URL_DEFAULT="${SCITEX_OROCHI_HUB_URL:-https://scitex-orochi.com}"
# Trim any trailing / from the hub URL to avoid // in endpoint path.
HUB_URL="${HUB_URL_DEFAULT%/}"
COOLDOWN_SECONDS="${AUTO_DISPATCH_COOLDOWN_SECONDS:-900}"     # 15 min
SUBAGENT_CAP="${AUTO_DISPATCH_SUBAGENT_CAP:-3}"
CURL_TIMEOUT="${AUTO_DISPATCH_CURL_TIMEOUT:-8}"

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
  printf 'auto-dispatch: cannot create state/log dirs\n' >&2
  exit 3
}
: > "$STATE_FILE.init" 2>/dev/null || true
rm -f "$STATE_FILE.init" 2>/dev/null || true

TS_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
NOW_EPOCH="$(date -u +%s)"
LOCAL_HOST="$(orochi_hostname -s 2>/dev/null || orochi_hostname)"

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG_FILE"; }
stderr() { printf '%s\n' "$*" >&2; }

# Worst-severity aggregator. 0 ok  1 advisory  2 warn  3 critical
worst_exit=0
bump_exit() {
  local code="$1"
  if [ "$code" -gt "$worst_exit" ]; then
    worst_exit="$code"
  fi
}

# -----------------------------------------------------------------------------
# Kill switch — silent exit 0, no log noise beyond one line.
# -----------------------------------------------------------------------------
if [ "${SCITEX_AUTO_DISPATCH_DISABLED:-0}" = "1" ]; then
  log "disabled via SCITEX_AUTO_DISPATCH_DISABLED=1 — no-op"
  exit 0
fi

# -----------------------------------------------------------------------------
# Preflight: gh authenticated? If not, log + exit 0 — do not crash the
# scheduler. Same treatment for curl missing.
# -----------------------------------------------------------------------------
if ! command -v gh >/dev/null 2>&1; then
  log "skip: gh not installed"
  exit 0
fi
if ! gh auth status >/dev/null 2>&1; then
  log "skip: gh not authenticated"
  exit 0
fi
if ! command -v curl >/dev/null 2>&1; then
  log "skip: curl not installed"
  exit 0
fi

# -----------------------------------------------------------------------------
# Lane table — label the picker filters on, per fleet host.
#
# Source of truth: spec (lead msg#15975). Kept as a bash function so the
# mapping is local to this script and grep-able.
# -----------------------------------------------------------------------------
lane_for_host() {
  case "$1" in
    mba)            printf 'infrastructure' ;;    # primary: infra + hub-admin + scitex-cloud — start with infrastructure
    ywata-note-win) printf 'specialized-wsl-access' ;;
    spartan)        printf 'specialized-domain' ;;
    nas)            printf 'hub-admin' ;;
    *)              printf '' ;;
  esac
}

# -----------------------------------------------------------------------------
# parse_machines_yaml — same shape as host-liveness-probe (canonical_name
# list only here, we don't need aliases/sessions).
# -----------------------------------------------------------------------------
parse_machines_yaml() {
  if [ ! -f "$MACHINES_YAML" ]; then
    stderr "auto-dispatch: machines yaml missing: $MACHINES_YAML"
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
# fetch_hub_agents — GET /api/agents/ with workspace token.
# Prints the full JSON array on stdout when successful. On any error prints
# nothing and returns non-zero. Caller logs + decides severity.
# -----------------------------------------------------------------------------
fetch_hub_agents() {
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
    log "skip: no SCITEX_OROCHI_TOKEN"
    return 1
  fi

  local endpoint="$HUB_URL/api/agents/?token=$token"
  local http_code body tmp
  tmp="$(mktemp -t auto-dispatch.XXXXXX)"
  http_code="$(curl -sS -o "$tmp" -w '%{http_code}' \
      --max-time "$CURL_TIMEOUT" \
      -H 'Accept: application/json' \
      "$endpoint" 2>/dev/null || echo 000)"
  body="$(cat "$tmp" 2>/dev/null || true)"
  rm -f "$tmp" 2>/dev/null || true
  case "$http_code" in
    200) printf '%s' "$body"; return 0 ;;
    4*) log "hub 4xx ($http_code) — exit 0 per spec"; return 1 ;;
    *)  log "hub error ($http_code) — exit 0 per spec"; return 1 ;;
  esac
}

# -----------------------------------------------------------------------------
# State file — one line per head: "<host>\t<last_dispatch_epoch>\t<last_issue_num>"
# Cooldown helpers read + rewrite this file atomically.
# -----------------------------------------------------------------------------
state_get_last() {
  local host="$1"
  [ -f "$STATE_FILE" ] || { echo "0	0"; return; }
  awk -F'\t' -v h="$host" '$1==h { print $2 "\t" $3; found=1 } END { if (!found) print "0\t0" }' \
    "$STATE_FILE"
}

state_update() {
  local host="$1" epoch="$2" issue="$3"
  local tmp
  tmp="$(mktemp -t auto-dispatch-state.XXXXXX)"
  if [ -f "$STATE_FILE" ]; then
    awk -F'\t' -v h="$host" '$1 != h { print }' "$STATE_FILE" >"$tmp" 2>/dev/null || true
  fi
  printf '%s\t%s\t%s\n' "$host" "$epoch" "$issue" >>"$tmp"
  mv -f "$tmp" "$STATE_FILE"
}

state_all_recent_issues() {
  # Issue numbers dispatched inside the cooldown window, across ALL hosts.
  # Feeds the picker's --exclude so two heads racing the same 5-min tick
  # don't both grab the same TODO.
  [ -f "$STATE_FILE" ] || return 0
  local cutoff=$((NOW_EPOCH - COOLDOWN_SECONDS))
  awk -F'\t' -v cutoff="$cutoff" '$2+0 >= cutoff && $3 ~ /^[0-9]+$/ { print $3 }' \
    "$STATE_FILE" | paste -sd, -
}

# -----------------------------------------------------------------------------
# probe_head — the per-host logic. Emits one NDJSON line on stdout.
# -----------------------------------------------------------------------------
probe_head() {
  local host="$1" agents_json="$2"
  local agent_name="head-$host"
  local decision="noop" reason="" orochi_subagent_count=-1 is_online=0 orochi_pane_state="unknown"
  local cooldown_remaining=0 issue_num="" issue_title=""

  # Extract this head's registry payload. We pass the JSON via env var
  # (not stdin) so a heredoc on python3 -c doesn't race the pipe. The
  # python helper writes three tab-separated fields:
  #   <found>\t<status>\t<orochi_subagent_count>\t<orochi_pane_state>
  # found="0" → no registry entry. orochi_pane_state falls back to "unknown".
  local fields
  fields="$(
    AGENTS_JSON="$agents_json" AGENT_NAME="$agent_name" python3 -c '
import json, os
name = os.environ["AGENT_NAME"]
try:
    data = json.loads(os.environ.get("AGENTS_JSON") or "[]")
except Exception:
    data = []
found = "0"
status = ""
count = 0
pane = "unknown"
for a in (data if isinstance(data, list) else []):
    if a.get("name") == name:
        found = "1"
        status = str(a.get("status") or "")
        count = int(a.get("orochi_subagent_count") or 0)
        m = a.get("metrics") or {}
        pane = str(m.get("orochi_pane_state") or a.get("orochi_pane_state") or "unknown")
        break
print(f"{found}\t{status}\t{count}\t{pane}")
' 2>/dev/null || echo $'0\t\t0\tunknown'
  )"

  local found
  IFS=$'\t' read -r found _status _count _pane <<<"$fields"
  orochi_subagent_count="${_count:-0}"
  orochi_pane_state="${_pane:-unknown}"
  if [ "${_status:-}" = "online" ]; then is_online=1; else is_online=0; fi

  if [ "$found" != "1" ]; then
    decision="skip"
    reason="no_registry_entry"
    bump_exit 2
    emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
      "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" "" ""
    return
  fi

  # ---------------------------------------------------------------------------
  # Gate 1: must be online.
  # ---------------------------------------------------------------------------
  if [ "$is_online" != "1" ]; then
    decision="skip"
    reason="agent_offline"
    emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
      "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" "" ""
    return
  fi

  # ---------------------------------------------------------------------------
  # Gate 2: upper bound — lead's cap. Already working enough, don't pile on.
  # ---------------------------------------------------------------------------
  if [ "$orochi_subagent_count" -ge "$SUBAGENT_CAP" ]; then
    decision="skip"
    reason="at_cap(${orochi_subagent_count}/${SUBAGENT_CAP})"
    bump_exit 1
    emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
      "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" "" ""
    return
  fi

  # ---------------------------------------------------------------------------
  # Gate 3: only act when orochi_subagent_count == 0. (1 or 2 — still working.)
  # ---------------------------------------------------------------------------
  if [ "$orochi_subagent_count" -ne 0 ]; then
    decision="noop"
    reason="orochi_subagent_count=${orochi_subagent_count}_within_working_band"
    emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
      "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" "" ""
    return
  fi

  # ---------------------------------------------------------------------------
  # Gate 4: cooldown. Don't re-inject within COOLDOWN_SECONDS of a prior
  # dispatch to this head — gives the head time to fork + the subagent to
  # start + the heartbeat to roll forward.
  # ---------------------------------------------------------------------------
  local last_line last_epoch last_issue
  last_line="$(state_get_last "$host")"
  last_epoch="${last_line%%	*}"
  last_issue="${last_line##*	}"
  : "${last_epoch:=0}"
  if [ "$last_epoch" -gt 0 ]; then
    local age=$((NOW_EPOCH - last_epoch))
    if [ "$age" -lt "$COOLDOWN_SECONDS" ]; then
      cooldown_remaining=$((COOLDOWN_SECONDS - age))
      decision="skip"
      reason="cooldown_${cooldown_remaining}s_remaining(last=#${last_issue})"
      bump_exit 1
      emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
        "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" "" ""
      return
    fi
  fi

  # ---------------------------------------------------------------------------
  # Gate 5: if pane classifier reports "busy", treat as still-working even
  # when orochi_subagent_count reads 0 — don't interrupt. The heartbeat publisher
  # occasionally misses a brief child window and we'd rather under-dispatch
  # than clobber an in-flight thinking step.
  # ---------------------------------------------------------------------------
  if [ "$orochi_pane_state" = "busy" ]; then
    decision="skip"
    reason="pane_busy"
    bump_exit 1
    emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
      "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" "" ""
    return
  fi

  # ---------------------------------------------------------------------------
  # Pick next TODO for this head's lane.
  # ---------------------------------------------------------------------------
  local lane
  lane="$(lane_for_host "$host")"
  if [ -z "$lane" ]; then
    decision="skip"
    reason="no_lane_mapping"
    bump_exit 1
    emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
      "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" "" ""
    return
  fi

  local exclude_csv pick_json
  exclude_csv="$(state_all_recent_issues)"
  if ! pick_json="$(python3 "$PICK_HELPER" --lane "$lane" ${exclude_csv:+--exclude "$exclude_csv"} 2>/dev/null)"; then
    decision="skip"
    reason="picker_failed"
    bump_exit 1
    emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
      "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" "" ""
    return
  fi
  if [ -z "$pick_json" ] || [ "$pick_json" = "null" ]; then
    decision="skip"
    reason="no_open_todo_for_lane=${lane}"
    bump_exit 1
    emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
      "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" "" ""
    return
  fi

  issue_num="$(printf '%s' "$pick_json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["number"])' 2>/dev/null || echo "")"
  issue_title="$(printf '%s' "$pick_json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["title"])' 2>/dev/null || echo "")"

  if [ -z "$issue_num" ]; then
    decision="skip"
    reason="pick_parse_failed"
    bump_exit 1
    emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
      "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" "" ""
    return
  fi

  # ---------------------------------------------------------------------------
  # Compose dispatch prompt and inject (or log, if --dry-run).
  # ---------------------------------------------------------------------------
  local prompt
  prompt="Auto-dispatch: please claim and fork a subagent for todo#${issue_num} — ${issue_title}. Reply \`claim #${issue_num}\` in #heads and proceed."

  if [ "$dry_run" -eq 1 ]; then
    decision="would_dispatch"
    reason="dry_run"
    log "DRY-RUN host=${host} todo=#${issue_num} lane=${lane}"
    # Note: we do NOT touch the state file in dry-run — cooldown is only
    # armed by actual dispatches, otherwise a dry-run tick would mask real
    # runs for 15 min.
  else
    if inject_dispatch "$host" "$agent_name" "$prompt"; then
      decision="dispatched"
      reason="tmux_send_keys_ok"
      state_update "$host" "$NOW_EPOCH" "$issue_num"
      log "DISPATCH host=${host} todo=#${issue_num} lane=${lane}"
    else
      decision="dispatch_failed"
      reason="tmux_send_keys_failed"
      bump_exit 1
      log "DISPATCH-FAIL host=${host} todo=#${issue_num} lane=${lane}"
    fi
  fi

  emit_ndjson "$host" "$agent_name" "$decision" "$reason" \
    "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown_remaining" \
    "$issue_num" "$issue_title"
}

# -----------------------------------------------------------------------------
# inject_dispatch — tmux send-keys into the head's session (window 0).
# Only called when dry_run==0 AND host == LOCAL_HOST (we don't auto-dispatch
# on remote hosts from here — each head's own launchd/cron runs this script
# locally for its own identity).
# -----------------------------------------------------------------------------
inject_dispatch() {
  local host="$1" agent="$2" prompt="$3"

  # Safety: do not SSH-inject into remote tmux. Each head auto-dispatches
  # for itself. If we're invoked on a box whose identity != "$host", warn
  # and return failure.
  local this_host
  this_host="$(resolve_self_host)"
  if [ "$this_host" != "$host" ]; then
    log "refuse remote-inject: this=${this_host} target=${host}"
    return 1
  fi

  if ! command -v tmux >/dev/null 2>&1; then
    log "tmux missing — cannot inject"
    return 1
  fi
  if ! tmux has-session -t "$agent" 2>/dev/null; then
    log "tmux session '${agent}' absent — cannot inject"
    return 1
  fi

  # send-keys with Enter. The single-quote escaping below assumes no
  # single quotes inside the issue title; we sanitise just in case.
  local sanitised
  sanitised="$(printf '%s' "$prompt" | tr -d '\r')"
  if tmux send-keys -t "${agent}:0" "$sanitised" Enter 2>/dev/null; then
    return 0
  fi
  return 1
}

# -----------------------------------------------------------------------------
# resolve_self_host — canonical fleet label for the box we're on.
# Re-uses scripts/client/resolve-orochi_hostname if present. Falls back to env /
# orochi_hostname -s.
# -----------------------------------------------------------------------------
resolve_self_host() {
  if [ -n "${SCITEX_OROCHI_HOSTNAME:-}" ]; then
    printf '%s' "$SCITEX_OROCHI_HOSTNAME"
    return
  fi
  if [ -x "$SCRIPT_DIR/resolve-orochi_hostname" ]; then
    local out
    out="$("$SCRIPT_DIR/resolve-orochi_hostname" 2>/dev/null)"
    if [ -n "$out" ]; then
      printf '%s' "$out"
      return
    fi
  fi
  printf '%s' "$LOCAL_HOST"
}

# -----------------------------------------------------------------------------
# emit_ndjson — one NDJSON line per probed head.
# -----------------------------------------------------------------------------
emit_ndjson() {
  local host="$1" agent="$2" decision="$3" reason="$4"
  local orochi_subagent_count="$5" is_online="$6" orochi_pane_state="$7" cooldown="$8"
  local issue_num="${9:-}" issue_title="${10:-}"
  python3 - "$TS_ISO" "$host" "$agent" "$decision" "$reason" \
                     "$orochi_subagent_count" "$is_online" "$orochi_pane_state" "$cooldown" \
                     "$issue_num" "$issue_title" "$dry_run" <<'PY'
import json, sys
ts, host, agent, decision, reason, sc, online, pane, cooldown, issue_num, issue_title, dry_run = sys.argv[1:]
obj = {
    "schema": "scitex-orochi/auto-dispatch-probe/v1",
    "ts": ts,
    "host": host,
    "agent": agent,
    "decision": decision,
    "reason": reason,
    "orochi_subagent_count": int(sc or 0),
    "online": online == "1",
    "orochi_pane_state": pane or "unknown",
    "cooldown_remaining_s": int(cooldown or 0),
    "issue_num": int(issue_num) if (issue_num or "").isdigit() else None,
    "issue_title": issue_title or "",
    "dry_run": dry_run == "1",
}
# NDJSON to stdout.
print(json.dumps(obj, separators=(",", ":"), sort_keys=False))
PY
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
  log "cycle start dry_run=${dry_run} only_host='${only_host}'"

  local heads
  if ! heads="$(parse_machines_yaml)"; then
    stderr "auto-dispatch: failed to parse $MACHINES_YAML"
    return 3
  fi
  if [ -z "$heads" ]; then
    stderr "auto-dispatch: no head-role machines in $MACHINES_YAML"
    return 3
  fi

  # Filter to only the local head unless --host overrides. The daemon's
  # contract is: run on each box, dispatch for that box only.
  local self
  self="$(resolve_self_host)"
  local target_host="${only_host:-$self}"

  # Quick membership check — target_host must be in heads list.
  if ! printf '%s\n' "$heads" | grep -qx "$target_host"; then
    log "target host '${target_host}' is not a head in machines yaml — exit 0"
    return 0
  fi

  local agents_json
  if ! agents_json="$(fetch_hub_agents)"; then
    # fetch_hub_agents already logged; benign exit 0 per spec.
    return 0
  fi
  if [ -z "$agents_json" ]; then
    log "hub returned empty agents list"
    bump_exit 2
    return "$worst_exit"
  fi

  probe_head "$target_host" "$agents_json"

  log "cycle end worst_severity_code=${worst_exit}"
  return "$worst_exit"
}

main
