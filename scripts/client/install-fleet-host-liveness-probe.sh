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

# todo#466: install a stable copy of the probe under ~/.scitex/orochi/bin/.
# Cron / launchd references the stable copy, NOT the shared working tree,
# so checking out a pre-PR#296 branch in the repo no longer silently 404s
# the scheduler. Updates propagate by re-running this installer.
SOURCE_PROBE="${REPO_ROOT}/scripts/client/fleet-watch/host-liveness-probe.sh"
STABLE_BIN_DIR="${HOME}/.scitex/orochi/bin"
STABLE_PROBE="${STABLE_BIN_DIR}/host-liveness-probe.sh"
# Sibling helpers the probe dynamically sources. Copy each alongside the
# probe if it exists in the working tree; installer is forward-compatible
# with helpers added post-merge.
SOURCE_SIBLINGS=(
    "${REPO_ROOT}/scripts/client/fleet-watch/revive_rate_limit.py"
)

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
# Stable bin install (todo#466)
#
# Copies the probe + siblings into ~/.scitex/orochi/bin/ so the scheduler
# does not reference files inside the shared working tree. Idempotent:
# re-running on install overwrites the stable copy with the tree version,
# which is how updates propagate.
# -----------------------------------------------------------------------------
install_stable_probe() {
    if [[ ! -f "$SOURCE_PROBE" ]]; then
        echo "probe source missing: $SOURCE_PROBE" >&2
        exit 1
    fi
    mkdir -p "$STABLE_BIN_DIR"
    cp -f "$SOURCE_PROBE" "$STABLE_PROBE"
    chmod +x "$STABLE_PROBE"
    local sib name
    for sib in "${SOURCE_SIBLINGS[@]}"; do
        if [[ -f "$sib" ]]; then
            name="$(basename "$sib")"
            cp -f "$sib" "${STABLE_BIN_DIR}/${name}"
            # Preserve exec bit for shell/py helpers the probe may shell out to.
            if [[ -x "$sib" ]]; then
                chmod +x "${STABLE_BIN_DIR}/${name}"
            fi
        fi
    done
    echo "stable probe: $STABLE_PROBE (repo=$REPO_ROOT)"
}

uninstall_stable_probe() {
    # Only remove files we own; preserve the bin dir in case other tools
    # also install there.
    local sib name
    rm -f "$STABLE_PROBE"
    for sib in "${SOURCE_SIBLINGS[@]}"; do
        name="$(basename "$sib")"
        rm -f "${STABLE_BIN_DIR}/${name}"
    done
    echo "uninstalled stable probe: $STABLE_PROBE"
}

# -----------------------------------------------------------------------------
# macOS (LaunchAgent)
# -----------------------------------------------------------------------------
install_macos() {
    if [[ ! -f "$TEMPLATE" ]]; then
        echo "template missing: $TEMPLATE" >&2
        exit 1
    fi
    install_stable_probe
    mkdir -p "$(dirname "$TARGET_LAUNCHD")" "$MAC_LOG_DIR"

    # The plist template still carries __REPO__ for backward-compat (e.g.
    # if we ever add more binaries there), but ProgramArguments now points
    # at the stable bin copy via __STABLE_PROBE__. We also inject
    # SCITEX_OROCHI_REPO_ROOT into EnvironmentVariables so the stable-copy
    # probe can locate orochi-machines.yaml.
    local esc_home esc_repo esc_stable
    esc_home="$(printf '%s' "$HOME" | sed 's|[|&]|\\&|g')"
    esc_repo="$(printf '%s' "$REPO_ROOT" | sed 's|[|&]|\\&|g')"
    esc_stable="$(printf '%s' "$STABLE_PROBE" | sed 's|[|&]|\\&|g')"
    sed -e "s|__HOME__|${esc_home}|g" \
        -e "s|__REPO__|${esc_repo}|g" \
        -e "s|__STABLE_PROBE__|${esc_stable}|g" \
        -e "s|__PROBE_MODE__|${mode}|g" \
        "$TEMPLATE" > "$TARGET_LAUNCHD"

    launchctl unload "$TARGET_LAUNCHD" 2>/dev/null || true
    launchctl load "$TARGET_LAUNCHD"

    echo "installed: $TARGET_LAUNCHD"
    echo "probe:     $STABLE_PROBE"
    echo "repo_root: $REPO_ROOT (injected as SCITEX_OROCHI_REPO_ROOT)"
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
    uninstall_stable_probe
}

# -----------------------------------------------------------------------------
# Linux (user crontab)
# -----------------------------------------------------------------------------
CRON_MARKER="# scitex-orochi host-liveness-probe (todo#271)"
# Cron format (todo#466): pin SCITEX_OROCHI_REPO_ROOT inline so the
# stable-bin copy can locate orochi-machines.yaml; run the stable copy,
# not the working-tree path, so feature-branch checkouts never 404 the
# scheduler.
CRON_LINE_FMT='*/5 * * * * SCITEX_OROCHI_REPO_ROOT=%s %s %s >> %s/fleet-host-liveness-probe.log 2>&1'

install_linux() {
    install_stable_probe
    mkdir -p "$LINUX_LOG_DIR"
    local existing
    existing="$(crontab -l 2>/dev/null || true)"

    # Idempotent: if marker present, replace; else append.
    local new_line
    new_line="$(printf "$CRON_LINE_FMT" "$REPO_ROOT" "$STABLE_PROBE" "$mode" "$LINUX_LOG_DIR")"

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
    echo "probe: $STABLE_PROBE"
    echo "repo:  $REPO_ROOT"
    echo "mode:  $mode"
    echo "log:   ${LINUX_LOG_DIR}/fleet-host-liveness-probe.log"
    echo "view:  crontab -l"
}

uninstall_linux() {
    local existing
    existing="$(crontab -l 2>/dev/null || true)"
    if [ -z "$existing" ]; then
        echo "nothing to uninstall (empty crontab)"
        uninstall_stable_probe
        return 0
    fi
    if ! printf '%s\n' "$existing" | grep -qF "$CRON_MARKER"; then
        echo "nothing to uninstall (marker absent)"
        uninstall_stable_probe
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
    uninstall_stable_probe
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
