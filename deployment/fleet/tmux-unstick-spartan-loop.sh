#!/usr/bin/env bash
# tmux-unstick-spartan-loop.sh — Spartan-side wrapper
# -----------------------------------------------------------------------------
# Spartan login nodes have no per-user systemd and no passwordless sudo
# (per hpc-etiquette.md + memory feedback_sudo_scope.md). We run the
# unstick script as a user-space background while-loop invoked from
# .bash_profile / .bashrc or from the existing head-spartan startup
# wrapper.
#
# Install (add to ~/.bash_profile after the existing head-spartan
# tmux new-session -d block):
#
#   if ! pgrep -u "$USER" -f 'tmux-unstick-spartan-loop.sh' >/dev/null; then
#     nohup ~/proj/scitex-orochi/deployment/fleet/tmux-unstick-spartan-loop.sh \
#       >/dev/null 2>&1 &
#   fi
#
# The pgrep guard prevents multiple copies if the login shell re-runs
# the bash_profile.
#
# Cadence: 60 s (matches the MBA launchd and NAS/WSL systemd timer
# configurations so the fleet has a single unified poll rate).
# -----------------------------------------------------------------------------

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNSTICK_SCRIPT="$SCRIPT_DIR/tmux-unstick.sh"
INTERVAL="${UNSTICK_INTERVAL:-60}"

# Canonical runtime/ layout from dotfiles commit 68bd1592.
_LOGS_DIR="$HOME/.scitex/orochi/runtime/logs"
export LOG_FILE="${LOG_FILE:-$_LOGS_DIR/tmux-unstick.ndjson}"

mkdir -p "$(dirname "$LOG_FILE")"

# PID file so an external killer (agent-autostart rerun, etc) can cleanly stop us
PID_FILE="$_LOGS_DIR/tmux-unstick-loop.pid"
echo "$$" > "$PID_FILE"

trap 'rm -f "$PID_FILE"; exit 0' EXIT INT TERM

while true; do
  if [[ -x "$UNSTICK_SCRIPT" ]]; then
    bash "$UNSTICK_SCRIPT" --once >> "$_LOGS_DIR/tmux-unstick.loop.log" 2>&1 || true
  else
    printf '[%s] unstick script not executable: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$UNSTICK_SCRIPT" \
      >> "$_LOGS_DIR/tmux-unstick.loop.log"
  fi
  sleep "$INTERVAL"
done
