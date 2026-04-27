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

AGENT_DIR="${HOME}/.scitex/orochi/agents"
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

is_running() {
  local name="$1"
  tmux has-session -t "$name" 2>/dev/null
}

start_agent() {
  local name="$1"
  local yaml="${AGENT_DIR}/${name}/${name}.yaml"
  if [[ ! -f "$yaml" ]]; then
    echo "$(ts) SKIP: no yaml for $name" >> "$LOG"
    return 1
  fi
  if is_running "$name"; then
    return 0  # already running, silent
  fi
  echo "$(ts) STARTING: $name" >> "$LOG"
  scitex-agent-container start "$yaml" 2>>"$LOG" || {
    echo "$(ts) FAILED: $name" >> "$LOG"
    return 1
  }
  echo "$(ts) STARTED: $name" >> "$LOG"
  return 0
}

# If --check, just report status
if [[ "${1:-}" == "--check" ]]; then
  for dir in "${AGENT_DIR}"/*/; do
    name=$(basename "$dir")
    if is_running "$name"; then
      echo "  RUNNING: $name"
    else
      echo "  STOPPED: $name"
    fi
  done
  exit 0
fi

# If specific agent name given, start just that one
if [[ -n "${1:-}" && "$1" != "--"* ]]; then
  start_agent "$1"
  exit $?
fi

# Otherwise, start all agents for this host with throttling
started=0
for dir in "${AGENT_DIR}"/*/; do
  name=$(basename "$dir")
  yaml="${dir}/${name}.yaml"
  [[ -f "$yaml" ]] || continue

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
done

if (( started > 0 )); then
  echo "$(ts) Started $started agents on $HOST" >> "$LOG"
fi
