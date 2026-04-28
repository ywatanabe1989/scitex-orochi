#!/usr/bin/env bash
# fleet-agents-upgrade.sh — upgrade scitex-orochi across every fleet host.
#
# Why: producer-side dependencies (e.g. detect-secrets added in 0.15.6
# for the .env redaction rewrite) only take effect when each agent's
# Python env is upgraded. Without this, the fleet runs mixed versions
# and the stricter redaction never reaches the wire.
#
# What: SSHs every host listed in `orochi-machines.yaml`, captures the
# before-version, runs `pip install -U scitex-orochi`, and prints the
# after-version. Non-zero exit if any host failed to upgrade.
#
# Usage:
#   ./scripts/server/fleet-agents-upgrade.sh                # all hosts
#   ./scripts/server/fleet-agents-upgrade.sh --dry-run      # show what would run
#   ./scripts/server/fleet-agents-upgrade.sh --hosts mba,nas
#
# Convention: every fleet host is expected to have `scitex-orochi`
# importable from the SAME `python3` that the agent's heartbeat loop
# uses. If your host pins to a venv (e.g. `~/.env-3.11/bin/python3`)
# point ``SCITEX_OROCHI_PYTHON`` at it via the host's environment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INVENTORY="${REPO_ROOT}/orochi-machines.yaml"

DRY_RUN=0
HOST_FILTER=""
for arg in "$@"; do
    case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --hosts=*) HOST_FILTER="${arg#--hosts=}" ;;
    --hosts)
        shift
        HOST_FILTER="${1:-}"
        ;;
    -h | --help)
        sed -n '2,18p' "$0"
        exit 0
        ;;
    *)
        echo "unknown arg: $arg" >&2
        exit 64
        ;;
    esac
done

# --- Discover canonical hostnames from the inventory ------------------------
# Avoids a yaml dep — the file uses a stable two-space-indent shape we can
# grep. ywatanabe 2026-04-28.
ALL_HOSTS=$(grep -E "^\s*-\s*canonical_name:\s*\S+" "$INVENTORY" |
    awk '{print $NF}')

if [[ -n "$HOST_FILTER" ]]; then
    # Comma-separated subset.
    IFS=',' read -ra HOSTS <<<"$HOST_FILTER"
else
    # All hosts.
    readarray -t HOSTS <<<"$ALL_HOSTS"
fi

# --- Per-host upgrade helper ------------------------------------------------
# `${SCITEX_OROCHI_PYTHON:-python3}` and `$scitex_orochi.__version__`
# below are wrapped in single quotes ON PURPOSE — the variable must
# expand on the REMOTE host's shell, not locally. ShellCheck flags this
# as SC2016; that's the correct behavior here.
# shellcheck disable=SC2016
upgrade_one() {
    local host="$1"
    local prefix="[$host]"

    if [[ "$DRY_RUN" == 1 ]]; then
        printf '%s DRY: ssh %s "${SCITEX_OROCHI_PYTHON:-python3} -m pip install -U scitex-orochi"\n' \
            "$prefix" "$host"
        return 0
    fi

    local before after
    before=$(ssh -o ConnectTimeout=5 "$host" \
        '${SCITEX_OROCHI_PYTHON:-python3} -c "import scitex_orochi; print(scitex_orochi.__version__)" 2>/dev/null' \
        2>/dev/null || echo "unreachable")

    if [[ "$before" == "unreachable" || -z "$before" ]]; then
        printf '%s ✗ unreachable or scitex_orochi not importable\n' "$prefix" >&2
        return 1
    fi

    printf '%s before: %s — upgrading…\n' "$prefix" "$before"
    if ! ssh -o ConnectTimeout=10 "$host" \
        '${SCITEX_OROCHI_PYTHON:-python3} -m pip install -q -U "scitex-orochi"' \
        2>&1 | sed "s|^|$prefix pip: |" >&2; then
        printf '%s ✗ pip install failed\n' "$prefix" >&2
        return 1
    fi

    after=$(ssh -o ConnectTimeout=5 "$host" \
        '${SCITEX_OROCHI_PYTHON:-python3} -c "import scitex_orochi; print(scitex_orochi.__version__)"' \
        2>/dev/null || echo "unknown")

    if [[ "$before" == "$after" ]]; then
        printf '%s = %s (no change)\n' "$prefix" "$after"
    else
        printf '%s ✓ %s → %s\n' "$prefix" "$before" "$after"
    fi
}

# --- Drive the fleet --------------------------------------------------------
echo "fleet-agents-upgrade — ${#HOSTS[@]} host(s):" "${HOSTS[@]}"
echo

failed=0
for host in "${HOSTS[@]}"; do
    [[ -z "$host" ]] && continue
    if ! upgrade_one "$host"; then
        failed=$((failed + 1))
    fi
done

echo
if [[ "$failed" -gt 0 ]]; then
    echo "✗ ${failed} host(s) failed to upgrade"
    exit 1
fi
echo "✓ all hosts on the latest scitex-orochi"
