#!/usr/bin/env bash
# chrome-codesign-clone-watchdog.sh
#
# scitex-orochi#286 item 2.
#
# Reap the `/private/var/folders/*/*/X/com.google.Chrome.code_sign_clone`
# cache when it grows large. This is a known Chrome-on-macOS
# `codesign`-verification cache leak; the clone is harmless and Chrome
# does not depend on its presence. On the 2026-04-21 mba outage a single
# instance of this directory had grown to 13 GiB and contributed
# directly to the host hitting 100% full (see
# `skills/infra-hub-docker-disk-full.md`, 2026-04-21 incident
# playbook).
#
# Usage:
#   chrome-codesign-clone-watchdog.sh             # default thresholds
#   chrome-codesign-clone-watchdog.sh --dry-run   # report only, never delete
#   ADVISE_GIB=1 REAP_GIB=8 chrome-codesign-clone-watchdog.sh
#
# Thresholds (gibibytes):
#   ADVISE_GIB (default 2) — log an advisory when total size ≥ this.
#   REAP_GIB   (default 5) — delete the directory when total size ≥ this.
#
# Exit codes:
#   0 — ran to completion (nothing found, or advisory, or reap).
#   1 — failed to probe or delete (see stderr).
#
# The watchdog is read-mostly: it stats via `du -sk`, never writes
# anything except the `rm -rf` on the exact codesign-clone path. It
# does not touch any other cache, any user data, or any Chrome
# profile state.

set -euo pipefail

ADVISE_GIB="${ADVISE_GIB:-2}"
REAP_GIB="${REAP_GIB:-5}"
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "chrome-codesign-clone-watchdog: unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

log() {
    printf '[%s] chrome-codesign-clone-watchdog: %s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

# Locate every Chrome code_sign_clone directory on this host. macOS
# per-user temp paths live under /private/var/folders/<hash>/<hash>/X/.
# Glob nulls if no matches; guard with nullglob.
shopt -s nullglob
CANDIDATES=( /private/var/folders/*/*/X/com.google.Chrome.code_sign_clone )
shopt -u nullglob

if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    log "no Chrome code_sign_clone paths found — nothing to do"
    exit 0
fi

advise_kib=$((ADVISE_GIB * 1024 * 1024))
reap_kib=$((REAP_GIB * 1024 * 1024))

for path in "${CANDIDATES[@]}"; do
    if [[ ! -d "$path" ]]; then
        continue
    fi
    # -s total; -k kibibytes for predictable arithmetic. Drop stderr so
    # sub-tree access errors don't abort the check.
    kib="$(du -sk "$path" 2>/dev/null | awk '{print $1}')"
    if [[ -z "$kib" ]]; then
        log "ERROR: failed to size $path"
        exit 1
    fi
    gib=$(( kib / 1024 / 1024 ))

    if (( kib >= reap_kib )); then
        if (( DRY_RUN )); then
            log "WOULD REAP $path (${gib} GiB ≥ ${REAP_GIB} GiB) — dry run"
        else
            log "REAPING $path (${gib} GiB ≥ ${REAP_GIB} GiB)"
            if rm -rf -- "$path"; then
                log "reaped $path"
            else
                log "ERROR: rm -rf failed for $path"
                exit 1
            fi
        fi
    elif (( kib >= advise_kib )); then
        log "ADVISORY $path is ${gib} GiB (≥ ${ADVISE_GIB} GiB, < ${REAP_GIB} GiB reap threshold)"
    else
        log "OK $path is ${gib} GiB (< ${ADVISE_GIB} GiB)"
    fi
done
