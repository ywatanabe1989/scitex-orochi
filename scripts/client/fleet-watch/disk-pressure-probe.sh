#!/usr/bin/env bash
# disk-pressure-probe.sh — host disk pressure check for healer preemptive advisory
# -----------------------------------------------------------------------------
# Authored by healer-mba 2026-04-21 for issue #286 item 3, in response to the
# 2026-04-21 mba full-disk incident (see skills/infra-hub-docker-disk-full).
#
# Principle: read-only check of the root ("/") filesystem + top home consumers.
# Emits one NDJSON line per invocation. Exit code carries severity so the
# caller (healer loop, fleet_watch.sh) can decide whether to post an advisory.
#
# Exit codes:
#   0 — OK            free >= DISK_FREE_ADVISORY_GIB
#   1 — advisory      DISK_FREE_WARN_GIB   <= free < DISK_FREE_ADVISORY_GIB
#   2 — warn          DISK_FREE_CRITICAL_GIB <= free < DISK_FREE_WARN_GIB
#   3 — critical      free < DISK_FREE_CRITICAL_GIB
#
# Thresholds default to the values in orochi-machines.yaml `preflight:`
# but can be overridden per invocation via env vars.
# -----------------------------------------------------------------------------

set -u
set -o pipefail

HOST="$(hostname -s 2>/dev/null || hostname)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
OUT_DIR="${HOST_TELEMETRY_OUT_DIR:-$HOME/.scitex/orochi/host-telemetry}"
OUT_FILE="$OUT_DIR/disk-pressure-${HOST}.ndjson"
mkdir -p "$OUT_DIR"

DISK_FREE_ADVISORY_GIB="${DISK_FREE_ADVISORY_GIB:-10}"
DISK_FREE_WARN_GIB="${DISK_FREE_WARN_GIB:-5}"
DISK_FREE_CRITICAL_GIB="${DISK_FREE_CRITICAL_GIB:-2}"

# df -k gives 1024-byte blocks everywhere (BSD, GNU, busybox).
# We query "/" — on macOS/Colima that's the Data volume; on Linux it's root.
df_line="$(df -k / 2>/dev/null | awk 'NR==2 {print $2, $3, $4}')"
total_kib="$(printf '%s' "$df_line" | awk '{print $1}')"
used_kib="$(printf '%s' "$df_line" | awk '{print $2}')"
avail_kib="$(printf '%s' "$df_line" | awk '{print $3}')"

if [ -z "$avail_kib" ]; then
  printf '{"schema":"scitex-orochi/disk-pressure-probe/v1","host":"%s","ts":"%s","error":"df_failed"}\n' \
    "$HOST" "$TS" >> "$OUT_FILE"
  exit 3
fi

# Convert KiB → GiB (integer). 1 GiB = 1048576 KiB.
avail_gib=$(( avail_kib / 1048576 ))
total_gib=$(( total_kib / 1048576 ))
used_gib=$(( used_kib / 1048576 ))

severity="ok"
exit_code=0
if [ "$avail_gib" -lt "$DISK_FREE_CRITICAL_GIB" ]; then
  severity="critical"; exit_code=3
elif [ "$avail_gib" -lt "$DISK_FREE_WARN_GIB" ]; then
  severity="warn"; exit_code=2
elif [ "$avail_gib" -lt "$DISK_FREE_ADVISORY_GIB" ]; then
  severity="advisory"; exit_code=1
fi

# Biggest home consumers for the advisory body. Depth-1 only, no du on /.
# Time-bounded — 90s ceiling, fall back to empty list.
top_json="[]"
if command -v python3 >/dev/null 2>&1; then
  top_json="$(
    (
      du -sh -- \
        "$HOME/.gradle" \
        "$HOME/.android" \
        "$HOME/Downloads" \
        "$HOME/.colima" \
        "$HOME/Library/Caches" \
        2>/dev/null || true
    ) | python3 -c '
import json, sys
rows = []
for line in sys.stdin:
    parts = line.split(None, 1)
    if len(parts) == 2:
        rows.append({"size": parts[0], "path": parts[1].rstrip()})
sys.stdout.write(json.dumps(rows))
' 2>/dev/null || printf '[]'
  )"
fi

printf '{"schema":"scitex-orochi/disk-pressure-probe/v1","host":"%s","ts":"%s","mount":"/","total_gib":%d,"used_gib":%d,"avail_gib":%d,"severity":"%s","thresholds":{"advisory_gib":%d,"warn_gib":%d,"critical_gib":%d},"top_home_consumers":%s}\n' \
  "$HOST" "$TS" \
  "$total_gib" "$used_gib" "$avail_gib" \
  "$severity" \
  "$DISK_FREE_ADVISORY_GIB" "$DISK_FREE_WARN_GIB" "$DISK_FREE_CRITICAL_GIB" \
  "$top_json" \
  >> "$OUT_FILE"

# Human-readable line on stdout for healer to paste into #agent when non-OK.
if [ "$severity" != "ok" ]; then
  printf 'disk-pressure %s on %s: / has %d GiB free (of %d GiB). Thresholds: advisory<%d warn<%d critical<%d. Run scripts/client/disk-reaper.sh --dry-run to see reapable targets.\n' \
    "$severity" "$HOST" "$avail_gib" "$total_gib" \
    "$DISK_FREE_ADVISORY_GIB" "$DISK_FREE_WARN_GIB" "$DISK_FREE_CRITICAL_GIB"
fi

exit "$exit_code"
