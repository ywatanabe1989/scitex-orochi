#!/usr/bin/env bash
# install-orochi-cron.sh
#
# Installer for the Orochi unified cron daemon (msg#16406 / msg#16410 /
# lead msg#16408). One Python process per host replaces the per-job
# scatter of launchd plists / systemd timers / crontab entries.
#
# What this does
# --------------
# 1. Copies scripts/server/orochi-cron.py to ~/.scitex/orochi/bin/
#    (stable-bin-path pattern; same shape as PR #326 todo#466).
# 2. Seeds ~/.scitex/orochi/cron.yaml from the example if absent.
#    Never overwrites an operator-edited copy.
# 3. Migrates existing per-job units: unloads them and backs them up
#    to ~/.scitex/orochi/cron-migrated-units/ so rollback is trivial
#    (just mv + launchctl load / systemctl --user enable).
# 4. Installs + loads the daemon-style unit:
#      macOS : ~/Library/LaunchAgents/com.scitex.orochi-cron.plist
#      Linux : ~/.config/systemd/user/scitex-orochi-cron.service
#
# Usage:
#   ./scripts/client/install-orochi-cron.sh                # install
#   ./scripts/client/install-orochi-cron.sh --uninstall    # remove daemon
#   ./scripts/client/install-orochi-cron.sh --no-migrate   # skip step 3
#   ./scripts/client/install-orochi-cron.sh --dry-run      # show actions only
#
# Rollback: the migrated units sit intact under
# ~/.scitex/orochi/cron-migrated-units/ with a README.md explaining
# how to reinstate them.

set -u
set -o pipefail

LABEL="com.scitex.orochi-cron"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

DAEMON_SRC="${REPO_ROOT}/scripts/server/orochi-cron.py"
STABLE_BIN_DIR="${HOME}/.scitex/orochi/bin"
STABLE_DAEMON="${STABLE_BIN_DIR}/orochi-cron.py"

CONFIG_DIR="${HOME}/.scitex/orochi"
CONFIG_TARGET="${CONFIG_DIR}/cron.yaml"
CONFIG_EXAMPLE="${REPO_ROOT}/deployment/host-setup/orochi-cron/cron.yaml.example"
MIGRATED_DIR="${CONFIG_DIR}/cron-migrated-units"

MAC_LOG_DIR="${HOME}/Library/Logs/scitex"
LINUX_LOG_DIR="${HOME}/.local/state/scitex/orochi-cron"

LAUNCHD_TEMPLATE="${REPO_ROOT}/deployment/host-setup/launchd/${LABEL}.plist"
LAUNCHD_TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"

SYSTEMD_UNIT_DIR="${HOME}/.config/systemd/user"
SYSTEMD_SERVICE_TEMPLATE="${REPO_ROOT}/deployment/host-setup/systemd/scitex-orochi-cron.service"
SYSTEMD_SERVICE_NAME="scitex-orochi-cron.service"

action="install"
migrate=1
dry_run=0

while [ $# -gt 0 ]; do
    case "$1" in
        --uninstall)  action="uninstall"; shift ;;
        --no-migrate) migrate=0; shift ;;
        --dry-run)    dry_run=1; shift ;;
        -h|--help)    sed -n '2,33p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

OS="$(uname -s)"

run() {
    if [ "$dry_run" = "1" ]; then
        printf '[dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

# -----------------------------------------------------------------------------
# Stable bin + config seeding
# -----------------------------------------------------------------------------
install_stable_daemon() {
    if [[ ! -f "$DAEMON_SRC" ]]; then
        echo "daemon source missing: $DAEMON_SRC" >&2
        exit 1
    fi
    run mkdir -p "$STABLE_BIN_DIR"
    run cp -f "$DAEMON_SRC" "$STABLE_DAEMON"
    run chmod +x "$STABLE_DAEMON"
    echo "stable daemon: $STABLE_DAEMON"
}

uninstall_stable_daemon() {
    run rm -f "$STABLE_DAEMON"
    echo "uninstalled stable daemon: $STABLE_DAEMON"
}

seed_config() {
    run mkdir -p "$CONFIG_DIR"
    if [[ -f "$CONFIG_TARGET" ]]; then
        echo "config exists (left as-is): $CONFIG_TARGET"
        return
    fi
    if [[ ! -f "$CONFIG_EXAMPLE" ]]; then
        echo "config example missing: $CONFIG_EXAMPLE" >&2
        exit 1
    fi
    run cp "$CONFIG_EXAMPLE" "$CONFIG_TARGET"
    echo "seeded config from example: $CONFIG_TARGET"
}

# -----------------------------------------------------------------------------
# Migrate per-job units out of the way. Preserved under MIGRATED_DIR
# so rollback is a single `mv` + `launchctl load` / `systemctl enable`.
# -----------------------------------------------------------------------------
MAC_LEGACY_LABELS=(
    "com.scitex.fleet-host-liveness-probe"
    "com.scitex.hungry-signal"
    "com.scitex.chrome-codesign-watchdog"
    "com.scitex.auto-dispatch-probe"
    "com.scitex.orochi.agent-meta-push"
)

LINUX_LEGACY_UNITS=(
    "scitex-hungry-signal.timer"
    "scitex-hungry-signal.service"
    "scitex-auto-dispatch-probe.timer"
    "scitex-auto-dispatch-probe.service"
)

LINUX_LEGACY_CRON_MARKERS=(
    "# scitex-orochi host-liveness-probe (todo#271)"
    "# scitex-orochi hungry-signal (lead msg#16310)"
)

migrate_macos() {
    run mkdir -p "$MIGRATED_DIR"
    for label in "${MAC_LEGACY_LABELS[@]}"; do
        local src="${HOME}/Library/LaunchAgents/${label}.plist"
        if [[ -f "$src" ]]; then
            echo "migrating $label"
            run launchctl unload "$src" 2>/dev/null || true
            run mv -f "$src" "${MIGRATED_DIR}/${label}.plist"
        fi
    done
    _write_rollback_readme_mac
}

_write_rollback_readme_mac() {
    if [ "$dry_run" = "1" ]; then return; fi
    cat > "${MIGRATED_DIR}/README.md" <<'EOF'
# Orochi cron — migrated per-job units

install-orochi-cron.sh moved these legacy LaunchAgents aside so the
unified daemon owns the schedule. They stay here so you can roll back.

## Rollback

    # 1. Stop the unified daemon
    launchctl unload ~/Library/LaunchAgents/com.scitex.orochi-cron.plist

    # 2. Reinstate a specific legacy agent
    mv ~/.scitex/orochi/cron-migrated-units/com.scitex.<name>.plist \
       ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/com.scitex.<name>.plist

    # Or everything at once: re-run the old install-*.sh scripts.
EOF
    echo "wrote rollback README: ${MIGRATED_DIR}/README.md"
}

migrate_linux_systemd() {
    command -v systemctl >/dev/null 2>&1 || return 0
    run mkdir -p "$MIGRATED_DIR"
    for unit in "${LINUX_LEGACY_UNITS[@]}"; do
        local src="${SYSTEMD_UNIT_DIR}/${unit}"
        if [[ -f "$src" ]]; then
            echo "migrating $unit"
            run systemctl --user disable --now "$unit" 2>/dev/null || true
            run mv -f "$src" "${MIGRATED_DIR}/${unit}"
        fi
    done
    run systemctl --user daemon-reload 2>/dev/null || true
    _write_rollback_readme_linux
}

_write_rollback_readme_linux() {
    if [ "$dry_run" = "1" ]; then return; fi
    cat > "${MIGRATED_DIR}/README.md" <<'EOF'
# Orochi cron — migrated per-job units

install-orochi-cron.sh moved these legacy systemd user units aside so
the unified daemon owns the schedule. They stay here so you can roll
back.

## Rollback

    # 1. Stop the unified daemon
    systemctl --user disable --now scitex-orochi-cron.service

    # 2. Reinstate a specific legacy unit
    mv ~/.scitex/orochi/cron-migrated-units/<unit> \
       ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now <unit>
EOF
}

migrate_linux_cron() {
    local existing
    existing="$(crontab -l 2>/dev/null || true)"
    [ -z "$existing" ] && return 0
    local touched=0
    local rebuilt="$existing"
    for marker in "${LINUX_LEGACY_CRON_MARKERS[@]}"; do
        if printf '%s\n' "$rebuilt" | grep -qF "$marker"; then
            rebuilt="$(printf '%s\n' "$rebuilt" | awk -v marker="$marker" '
                BEGIN { skip=0 }
                {
                    if ($0 == marker) { skip=2; next }
                    if (skip > 0)     { skip--; next }
                    print $0
                }
            ')"
            echo "migrated crontab marker: $marker"
            touched=1
        fi
    done
    if [ "$touched" -eq 1 ]; then
        if [ "$dry_run" = "0" ]; then
            printf '%s\n' "$rebuilt" | crontab -
        fi
    fi
}

# -----------------------------------------------------------------------------
# macOS install / uninstall
# -----------------------------------------------------------------------------
install_macos() {
    if [[ ! -f "$LAUNCHD_TEMPLATE" ]]; then
        echo "template missing: $LAUNCHD_TEMPLATE" >&2
        exit 1
    fi
    install_stable_daemon
    seed_config
    [ "$migrate" = "1" ] && migrate_macos

    run mkdir -p "$(dirname "$LAUNCHD_TARGET")" "$MAC_LOG_DIR"

    local esc_home esc_bin
    esc_home="$(printf '%s' "$HOME" | sed 's|[|&]|\\&|g')"
    esc_bin="$(printf '%s' "$STABLE_BIN_DIR" | sed 's|[|&]|\\&|g')"
    if [ "$dry_run" = "1" ]; then
        echo "[dry-run] would template plist into $LAUNCHD_TARGET"
    else
        sed -e "s|__HOME__|${esc_home}|g" \
            -e "s|__STABLE_BIN__|${esc_bin}|g" \
            "$LAUNCHD_TEMPLATE" > "$LAUNCHD_TARGET"
    fi

    run launchctl unload "$LAUNCHD_TARGET" 2>/dev/null || true
    run launchctl load "$LAUNCHD_TARGET"

    echo "installed: $LAUNCHD_TARGET"
    echo "config:    $CONFIG_TARGET"
    echo "daemon:    $STABLE_DAEMON"
    echo "log:       ${MAC_LOG_DIR}/orochi-cron.log"
    echo "status:    launchctl list | grep ${LABEL}"
    echo "introspect: scitex-orochi cron list"
}

uninstall_macos() {
    if [[ -f "$LAUNCHD_TARGET" ]]; then
        run launchctl unload "$LAUNCHD_TARGET" 2>/dev/null || true
        run rm -f "$LAUNCHD_TARGET"
        echo "uninstalled: $LAUNCHD_TARGET"
    else
        echo "nothing to uninstall (no $LAUNCHD_TARGET)"
    fi
    uninstall_stable_daemon
}

# -----------------------------------------------------------------------------
# Linux install / uninstall (systemd --user)
# -----------------------------------------------------------------------------
_systemd_user_available() {
    command -v systemctl >/dev/null 2>&1 && \
        systemctl --user status >/dev/null 2>&1
}

install_linux() {
    if [[ ! -f "$SYSTEMD_SERVICE_TEMPLATE" ]]; then
        echo "systemd template missing: $SYSTEMD_SERVICE_TEMPLATE" >&2
        exit 1
    fi
    if ! _systemd_user_available; then
        echo "systemd --user unavailable — unified cron requires a systemd user instance." >&2
        echo "Fallback to manual: run scripts/server/orochi-cron.py under your preferred supervisor." >&2
        exit 1
    fi
    install_stable_daemon
    seed_config
    if [ "$migrate" = "1" ]; then
        migrate_linux_systemd
        migrate_linux_cron
    fi
    run mkdir -p "$SYSTEMD_UNIT_DIR" "$LINUX_LOG_DIR"

    local esc_home esc_bin
    esc_home="$(printf '%s' "$HOME" | sed 's|[|&]|\\&|g')"
    esc_bin="$(printf '%s' "$STABLE_BIN_DIR" | sed 's|[|&]|\\&|g')"
    if [ "$dry_run" = "1" ]; then
        echo "[dry-run] would template service into $SYSTEMD_UNIT_DIR/$SYSTEMD_SERVICE_NAME"
    else
        sed -e "s|__HOME__|${esc_home}|g" \
            -e "s|__STABLE_BIN__|${esc_bin}|g" \
            "$SYSTEMD_SERVICE_TEMPLATE" > "$SYSTEMD_UNIT_DIR/$SYSTEMD_SERVICE_NAME"
    fi
    run systemctl --user daemon-reload
    run systemctl --user enable --now "$SYSTEMD_SERVICE_NAME"
    echo "installed: $SYSTEMD_UNIT_DIR/$SYSTEMD_SERVICE_NAME"
    echo "config:    $CONFIG_TARGET"
    echo "daemon:    $STABLE_DAEMON"
    echo "status:    systemctl --user status ${SYSTEMD_SERVICE_NAME}"
    echo "logs:      journalctl --user -u ${SYSTEMD_SERVICE_NAME}"
    echo "introspect: scitex-orochi cron list"
}

uninstall_linux() {
    if _systemd_user_available; then
        run systemctl --user disable --now "$SYSTEMD_SERVICE_NAME" 2>/dev/null || true
    fi
    if [[ -f "$SYSTEMD_UNIT_DIR/$SYSTEMD_SERVICE_NAME" ]]; then
        run rm -f "$SYSTEMD_UNIT_DIR/$SYSTEMD_SERVICE_NAME"
        run systemctl --user daemon-reload 2>/dev/null || true
        echo "uninstalled: $SYSTEMD_UNIT_DIR/$SYSTEMD_SERVICE_NAME"
    fi
    uninstall_stable_daemon
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
        echo "install-orochi-cron: unsupported OS ($OS)" >&2
        exit 2
        ;;
esac
