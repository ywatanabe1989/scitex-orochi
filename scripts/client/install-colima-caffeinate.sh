#!/usr/bin/env bash
# install-colima-caffeinate.sh — install/uninstall the colima-caffeinate
# LaunchDaemon on macOS hosts that run the orochi hub via colima.
#
# Why: macOS App Nap / Virtualization.framework can suspend the colima
# VM during host idle, dropping the SSH-MUX port-forward and surfacing
# as Cloudflare 502 bursts. caffeinate -dimsu -w <hostagent-pid> blocks
# the suspend. Installed as a LaunchDaemon so it survives reboot and
# runs without login. See
# ~/.scitex/orochi/shared/skills/scitex-orochi-private/infra-hub-stability.md
# for the post-mortem.
#
# Usage:
#   ./scripts/client/install-colima-caffeinate.sh                # install
#   ./scripts/client/install-colima-caffeinate.sh --uninstall    # remove
#   ./scripts/client/install-colima-caffeinate.sh --dry-run      # show actions only
#
# macOS only.

set -euo pipefail

LABEL="com.ywatanabe.colima-caffeinate"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${REPO_ROOT}/deployment/host-setup/launchd/${LABEL}.plist"
TARGET="/Library/LaunchDaemons/${LABEL}.plist"

UNINSTALL=0
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
    --uninstall) UNINSTALL=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h | --help)
        sed -n '2,20p' "$0"
        exit 0
        ;;
    *)
        echo "unknown arg: $arg" >&2
        exit 64
        ;;
    esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This installer is macOS-only (LaunchDaemon)." >&2
    exit 64
fi

run() {
    if [[ "$DRY_RUN" == "1" ]]; then
        printf 'DRY: %s\n' "$*"
    else
        # shellcheck disable=SC2294 # callers pass a single shell-string
        eval "$@"
    fi
}

if [[ "$UNINSTALL" == "1" ]]; then
    run "sudo launchctl bootout system/${LABEL} 2>/dev/null || true"
    run "sudo rm -f '${TARGET}'"
    echo "uninstalled ${LABEL}"
    exit 0
fi

if [[ ! -f "${TEMPLATE}" ]]; then
    echo "missing template: ${TEMPLATE}" >&2
    exit 65
fi

USERNAME="${USER:-$(/usr/bin/id -un)}"
HOMEDIR="${HOME:-/Users/${USERNAME}}"

# Render template with current username + home so logs land in the
# right place for whoever runs the installer.
RENDERED=$(/usr/bin/sed \
    -e "s|__USERNAME__|${USERNAME}|g" \
    -e "s|__HOME__|${HOMEDIR}|g" \
    "${TEMPLATE}")

TMP=$(/usr/bin/mktemp -t colima-caffeinate-plist)
trap 'rm -f "${TMP}"' EXIT
printf '%s\n' "${RENDERED}" >"${TMP}"

run "sudo cp -f '${TMP}' '${TARGET}'"
run "sudo chown root:wheel '${TARGET}'"
run "sudo chmod 644 '${TARGET}'"
run "sudo launchctl bootout system/${LABEL} 2>/dev/null || true"
run "sudo launchctl bootstrap system '${TARGET}'"

echo "installed ${LABEL} -> ${TARGET}"
echo "verify: launchctl print system/${LABEL} | head"
echo "logs:   tail -f ${HOMEDIR}/Library/Logs/colima-caffeinate.log"
