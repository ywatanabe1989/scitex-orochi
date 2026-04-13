#!/usr/bin/env bash
# NAS-side out-of-band fleet watcher (todo#282).
# Iterates over fleet hosts, runs probe_remote.sh inline via SSH, writes JSON snapshots.
# Designed to run from cron every 5 minutes on NAS.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROBE_SCRIPT="$SCRIPT_DIR/probe_remote.sh"
OUT_DIR="${FLEET_WATCH_OUT:-$HOME/.scitex/orochi/fleet-watch}"
LOG_FILE="$OUT_DIR/fleet_watch.log"
HOSTS=( mba spartan ywata-note-win )
SSH_TIMEOUT=8

mkdir -p "$OUT_DIR"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG_FILE"
}

probe_one() {
    local host="$1"
    local out_file="$OUT_DIR/${host}.json"
    local prev_file="$OUT_DIR/${host}.prev.json"
    local tmp_file="${out_file}.tmp"
    local container_file="${out_file}.container"

    # Rotate previous snapshot for diff comparison.
    if [ -s "$out_file" ]; then
        cp "$out_file" "$prev_file"
    fi

    timeout "$SSH_TIMEOUT" ssh \
            -o ConnectTimeout=5 \
            -o BatchMode=yes \
            -o StrictHostKeyChecking=accept-new \
            "$host" \
            "bash -s" <"$PROBE_SCRIPT" >"$tmp_file" 2>>"$LOG_FILE"
    local rc=$?

    # Validate output looks like JSON; otherwise fall back to unreachable.
    if [ $rc -ne 0 ] || ! head -c 1 "$tmp_file" 2>/dev/null | grep -q '{'; then
        log "FAIL ssh probe $host (rc=$rc, $(wc -c <"$tmp_file" 2>/dev/null) bytes)"
        printf '{"ts":"%s","host":"%s","reachable":false,"rc":%d}\n' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$host" "$rc" >"$tmp_file"
    fi

    # Forward-compatible second pass: pull scitex-agent-container status --json
    # if the host has it. Gracefully degrades when the binary is absent or the
    # context_management field has not landed yet (head-mba feat/context-manager).
    timeout "$SSH_TIMEOUT" ssh \
            -o ConnectTimeout=5 \
            -o BatchMode=yes \
            "$host" \
            'bash -lc "command -v scitex-agent-container >/dev/null 2>&1 && scitex-agent-container status --json 2>/dev/null"' \
            >"$container_file" 2>>"$LOG_FILE" || true

    # Merge container status into the snapshot if both are valid JSON.
    if [ -s "$container_file" ] && head -c 1 "$container_file" 2>/dev/null | grep -qE '\{|\['; then
        if command -v jq >/dev/null 2>&1; then
            jq -s '.[0] + {container_status: .[1]}' "$tmp_file" "$container_file" \
                > "${tmp_file}.merged" 2>>"$LOG_FILE" \
                && mv "${tmp_file}.merged" "$tmp_file"
        fi
    fi
    rm -f "$container_file"

    if [ -s "$tmp_file" ]; then
        mv "$tmp_file" "$out_file"
        log "ok $host bytes=$(wc -c <"$out_file" | tr -d ' ')"
        diff_one "$host" "$prev_file" "$out_file"
    else
        rm -f "$tmp_file"
        log "FAIL empty output $host"
    fi
}

# Compare key fields between prev and current snapshots, log anomalies.
# Conservative thresholds — only flags clearly meaningful changes.
diff_one() {
    local host="$1"
    local prev="$2"
    local curr="$3"

    [ -s "$prev" ] || return 0   # no baseline yet
    command -v jq >/dev/null 2>&1 || return 0

    local jq_diff
    jq_diff=$(jq -n \
        --slurpfile p "$prev" \
        --slurpfile c "$curr" \
        '
        ($p[0]) as $P | ($c[0]) as $C |
        {
            host: ($C.host // "?"),
            tmux_drop: (($P.tmux_count // 0) - ($C.tmux_count // 0)),
            tmux_lost: (
                (($P.tmux_names // "") | split(",")) -
                (($C.tmux_names // "") | split(","))
            ),
            tmux_gained: (
                (($C.tmux_names // "") | split(",")) -
                (($P.tmux_names // "") | split(","))
            ),
            fork_jump: (($C.fork_pressure_pct // 0) - ($P.fork_pressure_pct // 0)),
            claude_drop: (($P.claude_procs // 0) - ($C.claude_procs // 0)),
            became_unreachable: (($P.reachable // true) and (($C.reachable // true) | not))
        } |
        select(
            (.tmux_drop > 0) or
            (.fork_jump >= 10) or
            (.claude_drop > 0) or
            .became_unreachable or
            ((.tmux_lost | length) > 0)
        )
        ' 2>/dev/null)

    if [ -n "$jq_diff" ]; then
        log "ANOMALY $host: $(echo "$jq_diff" | tr -d '\n' | sed 's/  */ /g')"
    fi
}

# probe self locally too
probe_self() {
    local out_file="$OUT_DIR/nas.json"
    if [ -x "$PROBE_SCRIPT" ]; then
        bash "$PROBE_SCRIPT" >"$out_file" 2>>"$LOG_FILE" || log "FAIL local probe"
    fi
}

# Connectivity row producer (todo#297 PR B).
# After per-host probes finish, derive a per-peer connectivity matrix entry
# for THIS host (NAS) and write it to connectivity.json. Each per-host snapshot
# already contains a `reachable` field (or omits it on success); we measure
# RTT separately with a tiny ssh roundtrip per peer.
#
# Schema:
# {
#   "ts": "...",
#   "from": "nas",
#   "from_hostname": "DXP480TPLUS-994",
#   "to": {
#     "mba":            { "ok": true,  "rtt_ms": 12,  "route": "direct" },
#     "spartan":        { "ok": true,  "rtt_ms": 84,  "route": "direct" },
#     "ywata-note-win": { "ok": false, "rtt_ms": null,"route": "reverse-tunnel-1229", "error": "timeout" }
#   }
# }
#
# Hub consumption: file is read by mamba-healer-nas / scitex-orochi MCP tool
# `connectivity_matrix` (todo#297 layer 3). Once #298 fleet_report endpoint
# lands, this same row will also be POSTed to the hub for cross-host aggregation.
emit_connectivity_row() {
    local out_file="$OUT_DIR/connectivity.json"
    local tmp_file="${out_file}.tmp"
    local ts
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    {
        printf '{"ts":"%s","from":"nas","from_hostname":"%s","to":{' \
            "$ts" "$(hostname -s 2>/dev/null || hostname)"
        local first=1
        for h in "${HOSTS[@]}"; do
            local route="direct"
            case "$h" in
                ywata-note-win) route="reverse-tunnel-1229" ;;
            esac
            local start_ns end_ns rc rtt_ms ok err
            start_ns=$(date +%s%N)
            timeout "$SSH_TIMEOUT" ssh \
                    -o ConnectTimeout=5 \
                    -o BatchMode=yes \
                    "$h" "true" >/dev/null 2>>"$LOG_FILE"
            rc=$?
            end_ns=$(date +%s%N)
            if [ "$rc" -eq 0 ]; then
                rtt_ms=$(( (end_ns - start_ns) / 1000000 ))
                ok=true
                err=""
            else
                rtt_ms=null
                ok=false
                if [ "$rc" -eq 124 ]; then
                    err="timeout"
                else
                    err="exit_$rc"
                fi
            fi
            if [ "$first" -eq 1 ]; then
                first=0
            else
                printf ','
            fi
            if [ -n "$err" ]; then
                printf '"%s":{"ok":%s,"rtt_ms":%s,"route":"%s","error":"%s"}' \
                    "$h" "$ok" "$rtt_ms" "$route" "$err"
            else
                printf '"%s":{"ok":%s,"rtt_ms":%s,"route":"%s"}' \
                    "$h" "$ok" "$rtt_ms" "$route"
            fi
        done
        printf '}}\n'
    } >"$tmp_file"

    if [ -s "$tmp_file" ]; then
        mv "$tmp_file" "$out_file"
        log "ok connectivity row bytes=$(wc -c <"$out_file" | tr -d ' ')"
    else
        rm -f "$tmp_file"
        log "FAIL connectivity row (empty)"
    fi
}

main() {
    log "cycle start"
    probe_self
    for h in "${HOSTS[@]}"; do
        probe_one "$h"
    done
    emit_connectivity_row
    log "cycle end"
}

main "$@"
