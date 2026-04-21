#!/usr/bin/env bash
# install-worker-progress.sh
#
# Installer for the worker-progress headless daemon (todo#272).
#   macOS: installs a LaunchAgent that KeepAlive=true runs the daemon.
#   Linux: installs a systemd user unit that runs the daemon with
#          Restart=always.
#
# Usage:
#   ./scripts/client/install-worker-progress.sh           # install (live mode)
#   ./scripts/client/install-worker-progress.sh --dry-run # install in dry-run smoke mode
#   ./scripts/client/install-worker-progress.sh --uninstall
#
# Idempotent: safe to re-run.

set -u
set -o pipefail

LABEL="com.scitex.worker-progress"
# REPO_ROOT: this script lives at scripts/client/, so climb TWO levels
# to reach the repo root. Mirrors the corrected two-level climb from
# PR #297 (fix for the one-level bug introduced by PR #296's
# install-fleet-host-liveness-probe.sh).
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

TEMPLATE_PLIST="${REPO_ROOT}/deployment/host-setup/launchd/${LABEL}.plist"
TEMPLATE_SYSTEMD="${REPO_ROOT}/deployment/host-setup/systemd/scitex-worker-progress.service"
TARGET_LAUNCHD="${HOME}/Library/LaunchAgents/${LABEL}.plist"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
TARGET_SYSTEMD="${SYSTEMD_USER_DIR}/scitex-worker-progress.service"
MAC_LOG_DIR="${HOME}/Library/Logs/scitex"
LINUX_LOG_DIR="${HOME}/.local/state/scitex"

dry_run_flag=""
action="install"
while [ $# -gt 0 ]; do
    case "$1" in
        --uninstall) action="uninstall"; shift ;;
        --dry-run)   dry_run_flag="--dry-run"; shift ;;
        -h|--help)
            sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

OS="$(uname -s)"

# -----------------------------------------------------------------------------
# macOS (LaunchAgent)
# -----------------------------------------------------------------------------
install_macos() {
    if [[ ! -f "$TEMPLATE_PLIST" ]]; then
        echo "template missing: $TEMPLATE_PLIST" >&2
        exit 1
    fi
    mkdir -p "$(dirname "$TARGET_LAUNCHD")" "$MAC_LOG_DIR"

    local esc_home esc_repo
    esc_home="$(printf '%s' "$HOME" | sed 's|[|&]|\\&|g')"
    esc_repo="$(printf '%s' "$REPO_ROOT" | sed 's|[|&]|\\&|g')"

    # __DRY_RUN__ is the placeholder for the optional --dry-run arg.
    # When absent we replace with a repeat of the script path so the
    # ProgramArguments array still parses (launchd treats an empty
    # string argv entry as a literal "" which is fine, but we pick a
    # harmless arg for clarity in `ps` output).
    local dry_slot="${dry_run_flag:-}"
    if [[ -z "$dry_slot" ]]; then
        # Empty-string entry is valid; launchd/argparse just sees an empty
        # positional which argparse ignores. Cleaner than padding.
        dry_slot=""
    fi
    local esc_dry
    esc_dry="$(printf '%s' "$dry_slot" | sed 's|[|&]|\\&|g')"

    sed -e "s|__HOME__|${esc_home}|g" \
        -e "s|__REPO__|${esc_repo}|g" \
        -e "s|__DRY_RUN__|${esc_dry}|g" \
        "$TEMPLATE_PLIST" > "$TARGET_LAUNCHD"

    launchctl unload "$TARGET_LAUNCHD" 2>/dev/null || true
    launchctl load "$TARGET_LAUNCHD"

    echo "installed: $TARGET_LAUNCHD"
    echo "mode:      ${dry_run_flag:-live}"
    echo "log:       ${MAC_LOG_DIR}/worker-progress.log"
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
# Linux (systemd --user unit)
# -----------------------------------------------------------------------------
install_linux() {
    if [[ ! -f "$TEMPLATE_SYSTEMD" ]]; then
        echo "template missing: $TEMPLATE_SYSTEMD" >&2
        exit 1
    fi
    mkdir -p "$SYSTEMD_USER_DIR" "$LINUX_LOG_DIR"

    local esc_repo esc_dry
    esc_repo="$(printf '%s' "$REPO_ROOT" | sed 's|[|&]|\\&|g')"
    esc_dry="$(printf '%s' "${dry_run_flag:-}" | sed 's|[|&]|\\&|g')"

    sed -e "s|__REPO__|${esc_repo}|g" \
        -e "s|__DRY_RUN__|${esc_dry}|g" \
        "$TEMPLATE_SYSTEMD" > "$TARGET_SYSTEMD"

    systemctl --user daemon-reload
    systemctl --user enable --now scitex-worker-progress.service

    echo "installed: $TARGET_SYSTEMD"
    echo "mode:      ${dry_run_flag:-live}"
    echo "log:       ${LINUX_LOG_DIR}/worker-progress.log"
    echo "status:    systemctl --user status scitex-worker-progress.service"
    echo "journal:   journalctl --user -u scitex-worker-progress.service -f"
}

uninstall_linux() {
    if [[ ! -f "$TARGET_SYSTEMD" ]]; then
        echo "nothing to uninstall (no $TARGET_SYSTEMD)"
        return 0
    fi
    systemctl --user disable --now scitex-worker-progress.service 2>/dev/null || true
    rm -f "$TARGET_SYSTEMD"
    systemctl --user daemon-reload 2>/dev/null || true
    echo "uninstalled: $TARGET_SYSTEMD"
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
        echo "install-worker-progress: unsupported OS ($OS)" >&2
        exit 2
        ;;
esac
