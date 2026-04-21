#!/usr/bin/env bash
# install-chrome-codesign-watchdog.sh
#
# scitex-orochi#286 item 2 — install the Chrome code_sign_clone
# watchdog as a per-user LaunchAgent on macOS.
#
# Rewrites __HOME__ / __REPO__ in the template plist, copies it to
# ~/Library/LaunchAgents/, and loads it. Idempotent: unload + reload
# if an existing copy is present.
#
# Usage:
#   ./scripts/client/install-chrome-codesign-watchdog.sh
#   ./scripts/client/install-chrome-codesign-watchdog.sh --uninstall
#
# Only runs on macOS.

set -euo pipefail

LABEL="com.scitex.chrome-codesign-watchdog"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TEMPLATE="${REPO_ROOT}/deployment/host-setup/launchd/${LABEL}.plist"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/scitex"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "install-chrome-codesign-watchdog: macOS only (uname=$(uname -s))" >&2
    exit 2
fi

uninstall() {
    if [[ -f "$TARGET" ]]; then
        launchctl unload "$TARGET" 2>/dev/null || true
        rm -f "$TARGET"
        echo "uninstalled: $TARGET"
    else
        echo "nothing to uninstall (no $TARGET)"
    fi
}

case "${1:-}" in
    --uninstall) uninstall; exit 0 ;;
    "") ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
esac

if [[ ! -f "$TEMPLATE" ]]; then
    echo "template missing: $TEMPLATE" >&2
    exit 1
fi

mkdir -p "$(dirname "$TARGET")" "$LOG_DIR"

# Rewrite the template. Use sed with a delimiter unlikely to appear in
# a path (|) and escape any | in $HOME / $REPO_ROOT just in case.
esc_home="$(printf '%s' "$HOME" | sed 's|[|&]|\\&|g')"
esc_repo="$(printf '%s' "$REPO_ROOT" | sed 's|[|&]|\\&|g')"
sed -e "s|__HOME__|${esc_home}|g" -e "s|__REPO__|${esc_repo}|g" \
    "$TEMPLATE" > "$TARGET"

# Idempotent reload.
launchctl unload "$TARGET" 2>/dev/null || true
launchctl load "$TARGET"

echo "installed: $TARGET"
echo "log:       ${LOG_DIR}/chrome-codesign-watchdog.log"
echo "status:    launchctl list | grep ${LABEL}"
