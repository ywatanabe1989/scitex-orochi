#!/bin/bash
# install-launchd.sh — Generate and install LaunchAgent plists for all MBA agents.
# Lives in ~/proj/scitex-orochi/deployment/fleet/launchd/ (git-tracked).
#
# Usage:
#   ./install-launchd.sh              # install all MBA agents
#   ./install-launchd.sh --unload     # unload all
#   ./install-launchd.sh --status     # show load status

set -euo pipefail

TEMPLATE_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="${TEMPLATE_DIR}/com.scitex.orochi.AGENT_NAME.plist.template"
INSTALL_DIR="${HOME}/Library/LaunchAgents"
# Canonical post-68bd1592 layout: shared templates live under shared/agents/.
# ``AGENT_DIR`` is informational only — the template bakes the full path in
# the plist, so this path is not dereferenced here.
AGENT_DIR="${HOME}/.dotfiles/src/.scitex/orochi/shared/agents"

# MBA agents only
MBA_AGENTS=(
  head-mba
  mamba-auth-manager-mba
  mamba-explorer-mba
  mamba-healer-mba
  mamba-quality-checker-mba
  mamba-skill-manager-mba
  mamba-synchronizer-mba
  mamba-todo-manager-mba
  mamba-verifier-mba
)

if [[ "${1:-}" == "--unload" ]]; then
  for agent in "${MBA_AGENTS[@]}"; do
    plist="${INSTALL_DIR}/com.scitex.orochi.${agent}.plist"
    if [[ -f "$plist" ]]; then
      launchctl unload "$plist" 2>/dev/null && echo "Unloaded: $agent" || echo "Already unloaded: $agent"
    fi
  done
  exit 0
fi

if [[ "${1:-}" == "--status" ]]; then
  launchctl list 2>/dev/null | grep scitex.orochi || echo "No scitex.orochi agents loaded"
  exit 0
fi

# Generate and install
mkdir -p "$INSTALL_DIR"
for agent in "${MBA_AGENTS[@]}"; do
  plist="${INSTALL_DIR}/com.scitex.orochi.${agent}.plist"
  sed "s/AGENT_NAME/${agent}/g" "$TEMPLATE" > "$plist"
  echo "Generated: $plist"
done

echo ""
echo "To load all:  for f in ~/Library/LaunchAgents/com.scitex.orochi.*.plist; do launchctl load \"\$f\"; done"
echo "To unload all: $0 --unload"
