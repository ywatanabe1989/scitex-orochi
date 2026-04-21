#!/usr/bin/env bash
# install-fleet-host-liveness-probe.sh
#
# Installer for the fleet host-liveness probe scheduler (todo#271).
# On macOS: installs a LaunchAgent that runs the probe every 5 min.
# On Linux: appends a cron line (idempotent) that does the same.
#
# Default mode is `--yes` (auto-revive enabled) — the whole point of this
# PR is to stop losing agents silently. Use `--dry-run-only` to install
# the scheduler but run the probe in observation mode.
#
# Usage:
#   ./scripts/client/install-fleet-host-liveness-probe.sh           # install (--yes mode)
#   ./scripts/client/install-fleet-host-liveness-probe.sh --dry-run-only
#   ./scripts/client/install-fleet-host-liveness-probe.sh --uninstall

set -u
set -o pipefail

LABEL="com.scitex.fleet-host-liveness-probe"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TEMPLATE="${REPO_ROOT}/deployment/host-setup/launchd/${LABEL}.plist"
TARGET_LAUNCHD="${HOME}/Library/LaunchAgents/${LABEL}.plist"
MAC_LOG_DIR="${HOME}/Library/Logs/scitex"
LINUX_LOG_DIR="${HOME}/.local/state/scitex"
PROBE_SCRIPT="${REPO_ROOT}/scripts/client/fleet-watch/host-liveness-probe.sh"

mode="--yes"
action="install"
while [ $# -gt 0 ]; do
    case "$1" in
        --uninstall)    action="uninstall"; shift ;;
        --dry-run-only) mode="--dry-run"; shift ;;
        --yes)          mode="--yes"; shift ;;
        -h|--help)
            sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

OS="$(uname -s)"

# -----------------------------------------------------------------------------
# macOS (LaunchAgent)
# -----------------------------------------------------------------------------
install_macos() {
    if [[ ! -f "$TEMPLATE" ]]; then
        echo "template missing: $TEMPLATE" >&2
        exit 1
    fi
    mkdir -p "$(dirname "$TARGET_LAUNCHD")" "$MAC_LOG_DIR"

    local esc_home esc_repo
    esc_home="$(printf '%s' "$HOME" | sed 's|[|&]|\\&|g')"
    esc_repo="$(printf '%s' "$REPO_ROOT" | sed 's|[|&]|\\&|g')"
    sed -e "s|__HOME__|${esc_home}|g" \
        -e "s|__REPO__|${esc_repo}|g" \
        -e "s|__PROBE_MODE__|${mode}|g" \
        "$TEMPLATE" > "$TARGET_LAUNCHD"

    launchctl unload "$TARGET_LAUNCHD" 2>/dev/null || true
    launchctl load "$TARGET_LAUNCHD"

    echo "installed: $TARGET_LAUNCHD"
    echo "mode:      $mode"
    echo "log:       ${MAC_LOG_DIR}/fleet-host-liveness-probe.log"
    echo "status:    launchctl list | grep ${LABEL}"
}

uninstall_macos() {
    if [[ -f "$TARGET_LAUNCHD" ]]; then
        launchctl unload "$TARGET_LAUNCHD" 2>/dev/null || true
        rm -f "$TARGET_LAUNCHD"
        echo "uninstalled: $TARGET_LAUNCHD"
    else
        echo "nothing to uninstall (no $TARGET_LAUNCHD)"
    fi
}

# -----------------------------------------------------------------------------
# Linux (user crontab)
# -----------------------------------------------------------------------------
CRON_MARKER="# scitex-orochi host-liveness-probe (todo#271)"
CRON_LINE_FMT='*/5 * * * * %s %s >> %s/fleet-host-liveness-probe.log 2>&1'

install_linux() {
    mkdir -p "$LINUX_LOG_DIR"
    local existing
    existing="$(crontab -l 2>/dev/null || true)"

    # Idempotent: if marker present, replace; else append.
    local new_line
    new_line="$(printf "$CRON_LINE_FMT" "$PROBE_SCRIPT" "$mode" "$LINUX_LOG_DIR")"

    local rebuilt
    if printf '%s\n' "$existing" | grep -qF "$CRON_MARKER"; then
        # Replace the line following our marker.
        rebuilt="$(printf '%s\n' "$existing" | awk -v marker="$CRON_MARKER" -v line="$new_line" '
            BEGIN { printed=0 }
            {
                if ($0 == marker) {
                    print $0
                    getline next_line
                    print line
                    printed=1
                } else {
                    print $0
                }
            }
        ')"
    else
        rebuilt="${existing}
${CRON_MARKER}
${new_line}"
    fi

    printf '%s\n' "$rebuilt" | crontab -
    echo "installed crontab entry:"
    echo "  ${CRON_MARKER}"
    echo "  ${new_line}"
    echo "mode: $mode"
    echo "log:  ${LINUX_LOG_DIR}/fleet-host-liveness-probe.log"
    echo "view: crontab -l"
}

uninstall_linux() {
    local existing
    existing="$(crontab -l 2>/dev/null || true)"
    if [ -z "$existing" ]; then
        echo "nothing to uninstall (empty crontab)"
        return 0
    fi
    if ! printf '%s\n' "$existing" | grep -qF "$CRON_MARKER"; then
        echo "nothing to uninstall (marker absent)"
        return 0
    fi
    local rebuilt
    rebuilt="$(printf '%s\n' "$existing" | awk -v marker="$CRON_MARKER" '
        BEGIN { skip=0 }
        {
            if ($0 == marker) { skip=2; next }
            if (skip > 0)     { skip--; next }
            print $0
        }
    ')"
    printf '%s\n' "$rebuilt" | crontab -
    echo "uninstalled crontab marker + line"
}

# -----------------------------------------------------------------------------
# Dispatch
# -----------------------------------------------------------------------------
case "$OS" in
    Darwin)
        case "$action" in
            install)   install_macos ;;
            uninstall) uninstall_macos ;;
        esac
        ;;
    Linux)
        case "$action" in
            install)   install_linux ;;
            uninstall) uninstall_linux ;;
        esac
        ;;
    *)
        echo "install-fleet-host-liveness-probe: unsupported OS ($OS)" >&2
        exit 2
        ;;
esac
