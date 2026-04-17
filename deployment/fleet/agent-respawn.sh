#!/bin/bash
# agent-respawn.sh — Staged agent startup with throttling.
# Lives in ~/proj/scitex-orochi/deployment/fleet/ so it's git-tracked.
#
# Usage:
#   ./agent-respawn.sh                    # start all agents for this host
#   ./agent-respawn.sh head-mba           # start one specific agent
#   ./agent-respawn.sh --check            # check which agents are running
#
# Install as cron (every 5 min, checks and restarts dead agents):
#   */5 * * * * ~/proj/scitex-orochi/deployment/fleet/agent-respawn.sh >> /tmp/agent-respawn.log 2>&1

set -euo pipefail

# Canonical post-68bd1592 agent-definition roots, searched in order:
#   1. <host>/agents/        (host-specific)
#   2. shared/agents/        (shared template)
#   3. agents/               (legacy flat; DEPRECATED)
# The :- default is what `hostname -s` would give; users who want a short
# logical name set SCITEX_OROCHI_HOSTNAME in their shell rc.
HOST_NAME_FOR_AGENTS="${SCITEX_OROCHI_HOSTNAME:-$(hostname -s 2>/dev/null || hostname)}"
OROCHI_ROOT="${HOME}/.scitex/orochi"
AGENT_DIRS=(
  "${OROCHI_ROOT}/${HOST_NAME_FOR_AGENTS}/agents"
  "${OROCHI_ROOT}/shared/agents"
  "${OROCHI_ROOT}/agents"
)
# Back-compat alias for external callers that source this script and expect
# AGENT_DIR to be set.
AGENT_DIR="${OROCHI_ROOT}/agents"
LOG="/tmp/agent-respawn.log"
DELAY_BETWEEN=10  # seconds between agent starts to avoid reconnect storm

ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

# Detect current host
HOSTNAME=$(hostname -s 2>/dev/null || hostname)
case "$HOSTNAME" in
  *mba*|*MacBook*) HOST="mba" ;;
  *nas*|*UGREEN*)  HOST="nas" ;;
  *spartan*)       HOST="spartan" ;;
  *)               HOST="ywata-note-win" ;;
esac

# Resolve an agent name's yaml across the canonical roots (host/shared/legacy).
# Echoes the path on stdout, or nothing if not found.
_resolve_agent_yaml() {
  local name="$1"
  local root yaml
  for root in "${AGENT_DIRS[@]}"; do
    yaml="${root}/${name}/${name}.yaml"
    if [[ -f "$yaml" ]]; then
      printf '%s\n' "$yaml"
      return 0
    fi
  done
  return 1
}

is_running() {
  local name="$1"
  tmux has-session -t "$name" 2>/dev/null
}

start_agent() {
  local name="$1"
  local yaml
  yaml="$(_resolve_agent_yaml "$name" || true)"
  if [[ -z "$yaml" || ! -f "$yaml" ]]; then
    echo "$(ts) SKIP: no yaml for $name" >> "$LOG"
    return 1
  fi
  if is_running "$name"; then
    return 0  # already running, silent
  fi
  echo "$(ts) STARTING: $name (yaml=$yaml)" >> "$LOG"
  scitex-agent-container start "$yaml" 2>>"$LOG" || {
    echo "$(ts) FAILED: $name" >> "$LOG"
    return 1
  }
  echo "$(ts) STARTED: $name" >> "$LOG"
  return 0
}

# List unique agent names across the canonical roots.
_all_agent_names() {
  local root sub name
  declare -A seen=()
  for root in "${AGENT_DIRS[@]}"; do
    [[ -d "$root" ]] || continue
    for sub in "$root"/*/; do
      [[ -d "$sub" ]] || continue
      name="$(basename "$sub")"
      case "$name" in
        legacy|legacy-agents|_*) continue ;;
      esac
      if [[ -z "${seen[$name]+x}" ]]; then
        seen[$name]=1
        printf '%s\n' "$name"
      fi
    done
  done
}

# If --check, just report status
if [[ "${1:-}" == "--check" ]]; then
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    if is_running "$name"; then
      echo "  RUNNING: $name"
    else
      echo "  STOPPED: $name"
    fi
  done < <(_all_agent_names)
  exit 0
fi

# If specific agent name given, start just that one
if [[ -n "${1:-}" && "$1" != "--"* ]]; then
  start_agent "$1"
  exit $?
fi

# Otherwise, start all agents for this host with throttling
started=0
while IFS= read -r name; do
  [[ -n "$name" ]] || continue
  yaml="$(_resolve_agent_yaml "$name" || true)"
  [[ -n "$yaml" && -f "$yaml" ]] || continue

  # Check if this agent belongs to this host
  agent_host=$(grep -oP 'machine:\s*\K\S+' "$yaml" 2>/dev/null || echo "")
  if [[ -n "$agent_host" && "$agent_host" != "$HOST" ]]; then
    continue  # skip agents for other hosts
  fi

  if ! is_running "$name"; then
    start_agent "$name"
    started=$((started + 1))
    # Throttle: wait between starts to avoid reconnect storm
    if (( started > 0 )); then
      sleep "$DELAY_BETWEEN"
    fi
  fi
done < <(_all_agent_names)

if (( started > 0 )); then
  echo "$(ts) Started $started agents on $HOST" >> "$LOG"
fi
