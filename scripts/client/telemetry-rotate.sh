#!/usr/bin/env bash
# telemetry-rotate.sh — daily rotation + gzip + retention for NDJSON telemetry
# -----------------------------------------------------------------------------
# Rotates NDJSON files under ~/.scitex/orochi/orochi_runtime/{quota-telemetry,
# fleet-watch/{orochi_machine-info,ping,connection,process-info}}/ to prevent
# unbounded growth from 30-60s probe collectors.
#
# Policy:
#   1. For each *.ndjson in the watched dirs:
#      - If file mtime is before today UTC, rotate to *.ndjson.YYYY-MM-DD and
#        gzip in place (yesterday's snapshot sealed)
#   2. Delete any *.ndjson.*.gz older than RETENTION_DAYS (default 7)
#   3. Leave today's live *.ndjson untouched
#
# Usage:
#   telemetry-rotate.sh              # rotate + prune with defaults
#   RETENTION_DAYS=14 telemetry-rotate.sh
#   DRY_RUN=1 telemetry-rotate.sh    # print plan, no changes
#
# Intended to run once per day via launchd (~02:00 local).

set -euo pipefail

RETENTION_DAYS="${RETENTION_DAYS:-7}"
DRY_RUN="${DRY_RUN:-0}"

TELEMETRY_DIRS=(
    "${HOME}/.scitex/orochi/orochi_runtime/quota-telemetry"
    "${HOME}/.scitex/orochi/orochi_runtime/fleet-watch/orochi_machine-info"
    "${HOME}/.scitex/orochi/orochi_runtime/fleet-watch/ping"
    "${HOME}/.scitex/orochi/orochi_runtime/fleet-watch/connection"
    "${HOME}/.scitex/orochi/orochi_runtime/fleet-watch/process-info"
)

log() {
    printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

rotate_file() {
    local file="$1"
    local file_mtime_day
    local today_utc

    # Get file mtime day (UTC YYYY-MM-DD)
    file_mtime_day=$(date -u -r "$file" '+%Y-%m-%d')
    today_utc=$(date -u '+%Y-%m-%d')

    if [[ "$file_mtime_day" == "$today_utc" ]]; then
        return 0
    fi

    local target="${file}.${file_mtime_day}"
    local target_gz="${target}.gz"

    if [[ -e "$target_gz" ]]; then
        log "skip (already rotated): $file -> $target_gz"
        return 0
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
        log "DRY: mv $file $target && gzip $target"
    else
        mv "$file" "$target"
        gzip -9 "$target"
        log "rotated: $file -> $target_gz"
        # Recreate empty live file so collectors keep appending without
        # waiting for next probe to lazily create it.
        : >"$file"
    fi
}

prune_old() {
    local dir="$1"
    find "$dir" -type f -name '*.ndjson.*.gz' -mtime "+${RETENTION_DAYS}" -print0 2>/dev/null |
        while IFS= read -r -d '' f; do
            if [[ "$DRY_RUN" == "1" ]]; then
                log "DRY: rm $f"
            else
                rm -f "$f"
                log "pruned: $f (>${RETENTION_DAYS}d)"
            fi
        done
}

main() {
    local total_rotated=0

    for dir in "${TELEMETRY_DIRS[@]}"; do
        [[ -d "$dir" ]] || {
            log "skip (no dir): $dir"
            continue
        }

        # Rotate live NDJSON files
        while IFS= read -r -d '' file; do
            rotate_file "$file"
            total_rotated=$((total_rotated + 1))
        done < <(find "$dir" -maxdepth 1 -type f -name '*.ndjson' -print0 2>/dev/null)

        # Prune old gzipped snapshots
        prune_old "$dir"
    done

    log "rotate pass complete (checked ${total_rotated} live files, retention ${RETENTION_DAYS}d)"
}

main "$@"
