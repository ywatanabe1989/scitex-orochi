#!/usr/bin/env bash
# install-auto-dispatch-probe.sh
#
# Installer for the auto-dispatch probe scheduler — enforces "idle =
# forbidden" on each head by code instead of memory/rules.
#
# On macOS: installs a LaunchAgent that runs the probe every 5 min.
# On Linux: installs a systemd --user timer if available; else cron fallback.
#
# Two-level ../.. climb for REPO_ROOT — this script lives at
# scripts/client/install-auto-dispatch-probe.sh so the repo root is
# $(dirname "$0")/../.. (PR #297 fix; identical to
# install-fleet-host-liveness-probe.sh).
#
# Default mode is --yes (actual dispatch enabled). Use --dry-run-only to
# install the scheduler but only log "would-dispatch" decisions.
#
# Usage:
#   ./scripts/client/install-auto-dispatch-probe.sh              # install (--yes mode)
#   ./scripts/client/install-auto-dispatch-probe.sh --dry-run-only
#   ./scripts/client/install-auto-dispatch-probe.sh --uninstall

set -u
set -o pipefail

LABEL="com.scitex.auto-dispatch-probe"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TEMPLATE="${REPO_ROOT}/deployment/host-setup/launchd/${LABEL}.plist"
TARGET_LAUNCHD="${HOME}/Library/LaunchAgents/${LABEL}.plist"
MAC_LOG_DIR="${HOME}/Library/Logs/scitex"
LINUX_LOG_DIR="${HOME}/.local/state/scitex"
PROBE_SCRIPT="${REPO_ROOT}/scripts/client/auto-dispatch-probe.sh"

SYSTEMD_UNIT_DIR="${HOME}/.config/systemd/user"
SYSTEMD_SERVICE_TEMPLATE="${REPO_ROOT}/deployment/host-setup/systemd/scitex-auto-dispatch-probe.service"
SYSTEMD_TIMER_TEMPLATE="${REPO_ROOT}/deployment/host-setup/systemd/scitex-auto-dispatch-probe.timer"
SYSTEMD_SERVICE_NAME="scitex-auto-dispatch-probe.service"
SYSTEMD_TIMER_NAME="scitex-auto-dispatch-probe.timer"

mode="--yes"
action="install"
while [ $# -gt 0 ]; do
    case "$1" in
        --uninstall)    action="uninstall"; shift ;;
        --dry-run-only) mode="--dry-run"; shift ;;
        --yes)          mode="--yes"; shift ;;
        -h|--help)
            sed -n '2,25p' "$0"; exit 0 ;;
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
    if [[ ! -x "$PROBE_SCRIPT" ]]; then
        chmod +x "$PROBE_SCRIPT" 2>/dev/null || true
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
    echo "log:       ${MAC_LOG_DIR}/auto-dispatch.log"
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
# Linux — systemd --user if available, else cron.
# -----------------------------------------------------------------------------
CRON_MARKER="# scitex-orochi auto-dispatch-probe"
CRON_LINE_FMT='*/5 * * * * %s %s >> %s/auto-dispatch.log 2>&1'

_systemd_user_available() {
    command -v systemctl >/dev/null 2>&1 && \
        systemctl --user status >/dev/null 2>&1
}

install_linux_systemd() {
    if [[ ! -f "$SYSTEMD_SERVICE_TEMPLATE" ]] || [[ ! -f "$SYSTEMD_TIMER_TEMPLATE" ]]; then
        echo "systemd templates missing — falling back to cron" >&2
        return 1
    fi
    mkdir -p "$SYSTEMD_UNIT_DIR" "$LINUX_LOG_DIR"

    local esc_home esc_repo
    esc_home="$(printf '%s' "$HOME" | sed 's|[|&]|\\&|g')"
    esc_repo="$(printf '%s' "$REPO_ROOT" | sed 's|[|&]|\\&|g')"
    sed -e "s|__HOME__|${esc_home}|g" \
        -e "s|__REPO__|${esc_repo}|g" \
        -e "s|__PROBE_MODE__|${mode}|g" \
        "$SYSTEMD_SERVICE_TEMPLATE" > "$SYSTEMD_UNIT_DIR/$SYSTEMD_SERVICE_NAME"
    sed -e "s|__HOME__|${esc_home}|g" \
        -e "s|__REPO__|${esc_repo}|g" \
        "$SYSTEMD_TIMER_TEMPLATE" > "$SYSTEMD_UNIT_DIR/$SYSTEMD_TIMER_NAME"

    systemctl --user daemon-reload
    systemctl --user enable --now "$SYSTEMD_TIMER_NAME"
    echo "installed systemd user units in $SYSTEMD_UNIT_DIR"
    echo "  ${SYSTEMD_SERVICE_NAME}"
    echo "  ${SYSTEMD_TIMER_NAME}"
    echo "mode: $mode"
    echo "status: systemctl --user list-timers ${SYSTEMD_TIMER_NAME}"
    return 0
}

uninstall_linux_systemd() {
    if ! command -v systemctl >/dev/null 2>&1; then
        return 1
    fi
    systemctl --user disable --now "$SYSTEMD_TIMER_NAME" 2>/dev/null || true
    local removed=0
    if [[ -f "$SYSTEMD_UNIT_DIR/$SYSTEMD_TIMER_NAME" ]]; then
        rm -f "$SYSTEMD_UNIT_DIR/$SYSTEMD_TIMER_NAME"
        removed=1
    fi
    if [[ -f "$SYSTEMD_UNIT_DIR/$SYSTEMD_SERVICE_NAME" ]]; then
        rm -f "$SYSTEMD_UNIT_DIR/$SYSTEMD_SERVICE_NAME"
        removed=1
    fi
    if [ "$removed" -eq 1 ]; then
        systemctl --user daemon-reload 2>/dev/null || true
        echo "uninstalled systemd user units"
    fi
    return 0
}

install_linux_cron() {
    mkdir -p "$LINUX_LOG_DIR"
    local existing
    existing="$(crontab -l 2>/dev/null || true)"

    local new_line
    # shellcheck disable=SC2059
    new_line="$(printf "$CRON_LINE_FMT" "$PROBE_SCRIPT" "$mode" "$LINUX_LOG_DIR")"

    local rebuilt
    if printf '%s\n' "$existing" | grep -qF "$CRON_MARKER"; then
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
    echo "log:  ${LINUX_LOG_DIR}/auto-dispatch.log"
    echo "view: crontab -l"
}

uninstall_linux_cron() {
    local existing
    existing="$(crontab -l 2>/dev/null || true)"
    if [ -z "$existing" ]; then
        echo "nothing to uninstall (empty crontab)"
        return 0
    fi
    if ! printf '%s\n' "$existing" | grep -qF "$CRON_MARKER"; then
        echo "nothing to uninstall (cron marker absent)"
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

install_linux() {
    if _systemd_user_available && install_linux_systemd; then
        return 0
    fi
    install_linux_cron
}

uninstall_linux() {
    uninstall_linux_systemd || true
    uninstall_linux_cron || true
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
        echo "install-auto-dispatch-probe: unsupported OS ($OS)" >&2
        exit 2
        ;;
esac
