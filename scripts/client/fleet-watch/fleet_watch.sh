#!/usr/bin/env bash
# NAS-side out-of-band fleet watcher (todo#282).
# Iterates over fleet hosts, runs probe_remote.sh inline via SSH, writes JSON snapshots.
# Designed to run from cron every 5 minutes on NAS.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROBE_SCRIPT="$SCRIPT_DIR/probe_remote.sh"
DRIFT_SCRIPT="$SCRIPT_DIR/drift_check.py"
OUT_DIR="${FLEET_WATCH_OUT:-$HOME/.scitex/orochi/fleet-watch}"
LOG_FILE="$OUT_DIR/fleet_watch.log"
HOSTS=( mba spartan ywata-note-win )
SSH_TIMEOUT=8

# Map host alias → canonical head agent name, used by the
# scitex-agent-container snapshot --agent <name> --json call. The fallback
# bash probe (probe_remote.sh) is host-level and doesn't need this.
declare -A HEAD_AGENT
HEAD_AGENT[mba]=head-mba
HEAD_AGENT[spartan]=head-spartan
HEAD_AGENT[ywata-note-win]=head-ywata-note-win
HEAD_AGENT[nas]=head-nas

mkdir -p "$OUT_DIR"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG_FILE"
}

probe_one() {
    local host="$1"
    local out_file="$OUT_DIR/${host}.json"
    local prev_file="$OUT_DIR/${host}.prev.json"
    local tmp_file="${out_file}.tmp"
    local agent="${HEAD_AGENT[$host]:-head-$host}"

    # Rotate previous snapshot for diff comparison.
    if [ -s "$out_file" ]; then
        cp "$out_file" "$prev_file"
    fi

    # Pure-consumer path (todo#286 PR #18 / #21 landed): ask the remote
    # scitex-agent-container for its self-snapshot directly. This replaces
    # the legacy bash probe + status --json merge with a single round-trip
    # to a binary that already collects exactly what we need.
    local snapshot_rc=1
    timeout "$SSH_TIMEOUT" ssh \
            -o ConnectTimeout=5 \
            -o BatchMode=yes \
            -o StrictHostKeyChecking=accept-new \
            "$host" \
            "bash -lc 'scitex-agent-container snapshot --agent $agent --json 2>/dev/null'" \
            >"$tmp_file" 2>>"$LOG_FILE"
    snapshot_rc=$?
    if [ $snapshot_rc -eq 0 ] && head -c 1 "$tmp_file" 2>/dev/null | grep -q '{'; then
        # Snapshot succeeded — done.
        :
    else
        # Fallback path: probe_remote.sh inline (legacy behavior). Used
        # when the host doesn't have scitex-agent-container yet, the
        # snapshot subcommand returned non-JSON, or the agent isn't
        # registered. Keeps fleet_watch working through the migration.
        log "fallback probe_remote.sh for $host (snapshot rc=$snapshot_rc)"
        timeout "$SSH_TIMEOUT" ssh \
                -o ConnectTimeout=5 \
                -o BatchMode=yes \
                "$host" \
                "bash -s" <"$PROBE_SCRIPT" >"$tmp_file" 2>>"$LOG_FILE"
        local rc=$?
        if [ $rc -ne 0 ] || ! head -c 1 "$tmp_file" 2>/dev/null | grep -q '{'; then
            log "FAIL ssh probe $host (rc=$rc, $(wc -c <"$tmp_file" 2>/dev/null) bytes)"
            printf '{"ts":"%s","host":"%s","reachable":false,"rc":%d}\n' \
                "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$host" "$rc" >"$tmp_file"
        fi
    fi

    if [ -s "$tmp_file" ]; then
        mv "$tmp_file" "$out_file"
        log "ok $host bytes=$(wc -c <"$out_file" | tr -d ' ')"
        diff_one "$host" "$prev_file" "$out_file"
        classify_orochi_pane_state "$host" "$out_file" "$prev_file"
        check_drift "$host"
    else
        rm -f "$tmp_file"
        log "FAIL empty output $host"
    fi
}

# Compare orochi-machines.yaml expected_tmux_sessions vs the orochi_runtime
# snapshot. Logs any drift but does not escalate by itself — the
# DRIFT lines are picked up by mamba-healer-* via the log trail.
# Idempotent + read-only.
check_drift() {
    local host="$1"
    [ -x "$DRIFT_SCRIPT" ] || return 0
    command -v python3 >/dev/null 2>&1 || return 0
    local out
    out=$(FLEET_WATCH_OUT="$OUT_DIR" "$DRIFT_SCRIPT" "$host" 2>>"$LOG_FILE")
    if [ -n "$out" ]; then
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            log "$line"
        done <<<"$out"
    fi
}

# Classify an agent's pane state from agent_meta.orochi_pane_tail_block.
# Returns "busy" / "idle" / "stuck" / "unknown" per the canonical decision
# table in scitex-orochi/_skills/.../agent-health-check.md (#270 / #311).
#
# The new fields land in snapshot.agent_meta after PR #25 (cdbe9107).
# fleet_watch.sh receives them via the per-host snapshot path; the legacy
# bash probe_remote.sh fallback nests them under agents_meta.<name>.
#
# This function is informational — it does not by itself escalate. It logs
# `STATE host=<h> agent=<a> class=<c> stuck_cycles=N` so mamba-healer-* can
# read the trail and decide whether to act.
classify_orochi_pane_state() {
    local host="$1"
    local curr="$2"
    local prev="$3"
    command -v jq >/dev/null 2>&1 || return 0
    [ -s "$curr" ] || return 0

    # Pull every (agent, orochi_pane_tail_block) pair we can find. Both schemas:
    #   snapshot --json: .agent + .agent_meta.orochi_pane_tail_block          (single)
    #   probe_remote.sh fallback: .agents_meta.<name>.orochi_pane_tail_block  (map)
    local pairs
    pairs=$(jq -r '
        def pair($name; $block):
            if $block == null or $block == "" then empty
            else "\($name)\t\($block | tostring | @base64)" end;
        (
            (if .agent != null and (.agent_meta? // null) != null
              then pair(.agent; .agent_meta.orochi_pane_tail_block)
              else empty end),
            (
                (.agents_meta // {})
                | to_entries[]
                | pair(.key; .value.orochi_pane_tail_block)
            )
        )
    ' "$curr" 2>/dev/null)
    [ -z "$pairs" ] && return 0

    local prev_pairs=""
    if [ -s "$prev" ]; then
        prev_pairs=$(jq -r '
            def pair($name; $block):
                if $block == null or $block == "" then empty
                else "\($name)\t\($block | tostring | @base64)" end;
            (
                (if .agent != null and (.agent_meta? // null) != null
                  then pair(.agent; .agent_meta.orochi_pane_tail_block)
                  else empty end),
                (
                    (.agents_meta // {})
                    | to_entries[]
                    | pair(.key; .value.orochi_pane_tail_block)
                )
            )
        ' "$prev" 2>/dev/null)
    fi

    local stuck_state_dir="$OUT_DIR/state"
    mkdir -p "$stuck_state_dir"

    while IFS=$'\t' read -r agent block_b64; do
        [ -z "$agent" ] && continue
        local block
        block=$(printf '%s' "$block_b64" | base64 -d 2>/dev/null) || continue

        # Classification per agent-health-check.md decision table.
        local cls="unknown"
        case "$block" in
            *"Mulling…"*|*"Mulling..."*) cls="busy" ;;
            *"Working…"*|*"Working..."*) cls="busy" ;;
            *"Crunched"*) cls="busy" ;;
            *"Pondering…"*|*"Pondering..."*) cls="busy" ;;
            *"Press up to edit queued messages"*) cls="busy" ;;
            *"idle (ready for input)"*) cls="idle" ;;
            *"Idle"*) cls="idle" ;;
        esac
        # Empty prompt at end with no animation = ambiguous; leave "unknown"
        # for the cross-check against orochi presence (mamba-healer's role).

        # Stuck-cycle counter: if orochi_pane_tail_block matches the prev cycle,
        # increment a per-(host, agent) counter; otherwise reset.
        local stuck_file="$stuck_state_dir/${host}__${agent}.stuck"
        local stuck_n=0
        if [ -s "$stuck_file" ]; then
            stuck_n=$(cat "$stuck_file" 2>/dev/null | tr -d ' \n' || echo 0)
        fi
        local prev_block_b64
        prev_block_b64=$(printf '%s\n' "$prev_pairs" | awk -F'\t' -v a="$agent" '$1==a {print $2}' | head -1)
        if [ -n "$prev_block_b64" ] && [ "$prev_block_b64" = "$block_b64" ]; then
            stuck_n=$((stuck_n + 1))
        else
            stuck_n=0
        fi
        printf '%s\n' "$stuck_n" > "$stuck_file"

        log "STATE host=$host agent=$agent class=$cls stuck_cycles=$stuck_n"

        # Anomaly: stuck for >= 3 cycles (~15 min) AND class != busy
        # → output frozen, agent likely wedged. mamba-healer-* picks this up.
        if [ "$stuck_n" -ge 3 ] && [ "$cls" != "busy" ]; then
            log "ANOMALY $host $agent: pane unchanged for $stuck_n cycles, class=$cls (likely stuck)"
        fi
    done <<<"$pairs"
}

# Compare key fields between prev and current snapshots, log anomalies.
# Conservative thresholds — only flags clearly meaningful changes.
diff_one() {
    local host="$1"
    local prev="$2"
    local curr="$3"

    [ -s "$prev" ] || return 0   # no baseline yet
    command -v jq >/dev/null 2>&1 || return 0

    # tmux_names may be a comma-separated string (legacy probe_remote.sh
    # output) OR a JSON array (new snapshot --json output). Normalize both
    # via the `as_array` helper.
    local jq_diff
    jq_diff=$(jq -n \
        --slurpfile p "$prev" \
        --slurpfile c "$curr" \
        '
        def as_array(v):
            if v == null then []
            elif (v | type) == "array" then v
            elif (v | type) == "string" then (v | split(","))
            else [] end;
        ($p[0]) as $P | ($c[0]) as $C |
        (as_array($P.tmux_names)) as $pn |
        (as_array($C.tmux_names)) as $cn |
        {
            host: ($C.host // "?"),
            tmux_drop: (($P.tmux_count // 0) - ($C.tmux_count // 0)),
            tmux_lost: ($pn - $cn),
            tmux_gained: ($cn - $pn),
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
    local prev_file="$OUT_DIR/nas.prev.json"
    [ -x "$PROBE_SCRIPT" ] || return 0

    # Rotate latest -> prev for diff comparison.
    if [ -s "$out_file" ]; then
        cp "$out_file" "$prev_file"
    fi

    if bash "$PROBE_SCRIPT" >"${out_file}.tmp" 2>>"$LOG_FILE" && [ -s "${out_file}.tmp" ]; then
        mv "${out_file}.tmp" "$out_file"
        diff_one "nas" "$prev_file" "$out_file"
        classify_orochi_pane_state "nas" "$out_file" "$prev_file"
        check_drift "nas"
    else
        rm -f "${out_file}.tmp"
        log "FAIL local probe"
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
            "$ts" "$(orochi_hostname -s 2>/dev/null || orochi_hostname)"
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
        post_connectivity_to_hub "$out_file"
    else
        rm -f "$tmp_file"
        log "FAIL connectivity row (empty)"
    fi
}

# POST the latest connectivity row to the Orochi hub fleet_report endpoint
# (todo#298 / #297 hub side). Best-effort: silent on success, log on failure,
# never blocks the cycle. Token comes from the same dotfiles source file
# that other agents use; if neither $SCITEX_OROCHI_TOKEN nor the secrets
# file is reachable, we skip cleanly.
post_connectivity_to_hub() {
    local row_file="$1"
    [ -s "$row_file" ] || return 0
    command -v curl >/dev/null 2>&1 || { log "skip hub post (no curl)"; return 0; }

    local token="${SCITEX_OROCHI_TOKEN:-}"
    if [ -z "$token" ]; then
        local token_src="$HOME/.dotfiles/src/.bash.d/secrets/010_scitex/01_orochi.src"
        if [ -r "$token_src" ]; then
            # shellcheck disable=SC1090
            . "$token_src" 2>/dev/null || true
            token="${SCITEX_OROCHI_TOKEN:-}"
        fi
    fi
    if [ -z "$token" ]; then
        log "skip hub post (no SCITEX_OROCHI_TOKEN)"
        return 0
    fi

    local hub_url="${SCITEX_OROCHI_HUB_URL:-https://scitex-orochi.com}"
    local endpoint="$hub_url/api/fleet/report"

    # Build the wrapper envelope: entity_type=orochi_machine, entity_id=nas,
    # payload = the connectivity row JSON we just wrote.
    local wrapper_file="${row_file}.wrapper"
    if command -v jq >/dev/null 2>&1; then
        jq -n \
            --arg token "$token" \
            --arg entity_type "orochi_machine" \
            --arg entity_id "nas" \
            --arg source "head-nas" \
            --slurpfile payload "$row_file" \
            '{token: $token, entity_type: $entity_type, entity_id: $entity_id, source: $source, payload: $payload[0]}' \
            > "$wrapper_file" 2>>"$LOG_FILE" || { rm -f "$wrapper_file"; return 0; }
    else
        log "skip hub post (no jq for envelope)"
        return 0
    fi

    local http_code
    http_code=$(curl -sS -m 8 \
        -o /dev/null \
        -w '%{http_code}' \
        -H 'Content-Type: application/json' \
        -X POST \
        --data @"$wrapper_file" \
        "$endpoint" 2>>"$LOG_FILE")
    rm -f "$wrapper_file"

    case "$http_code" in
        200|201|202)
            log "hub post ok ($http_code)"
            ;;
        000)
            log "hub post FAIL (network)"
            ;;
        *)
            log "hub post FAIL ($http_code)"
            ;;
    esac
}

# Snapshot rotation policy (todo#300 NAS side).
# Cheap rotation that runs at the tail of every fleet_watch cycle:
#   - .json files older than ROTATE_AGE_HOURS get archived as .<YYYYMMDD>.json.gz
#   - .gz archives older than RETENTION_DAYS get deleted
# Live `*.json` (current-cycle snapshots) and `*.prev.json` (1-cycle-old)
# are NEVER touched — they're kept in place for the diff_one comparator and
# external consumers (mamba-healer-nas, connectivity_matrix MCP tool).
#
# Tunables via env (with sane defaults):
#   ROTATE_AGE_HOURS  default 24  — archive .json files older than this
#   RETENTION_DAYS    default 7   — delete .gz archives older than this
#
# Skips entirely when find/gzip are unavailable.
ROTATE_AGE_HOURS="${FLEET_WATCH_ROTATE_AGE_HOURS:-24}"
RETENTION_DAYS="${FLEET_WATCH_RETENTION_DAYS:-7}"

rotate_snapshots() {
    command -v find >/dev/null 2>&1 || { log "skip rotate (no find)"; return 0; }
    command -v gzip >/dev/null 2>&1 || { log "skip rotate (no gzip)"; return 0; }

    local age_minutes=$(( ROTATE_AGE_HOURS * 60 ))
    local archived=0
    local pruned=0

    # Archive eligible .json files (skip the 5 hot live names).
    while IFS= read -r -d '' f; do
        local base
        base=$(basename "$f")
        case "$base" in
            *.prev.json|*.tmp|*.tmp.merged) continue ;;
        esac
        # Skip the live current-cycle snapshots.
        case "$base" in
            mba.json|nas.json|spartan.json|ywata-note-win.json|connectivity.json) continue ;;
        esac
        local stamp
        stamp=$(date -u -r "$f" +%Y%m%d 2>/dev/null) || stamp=$(date -u +%Y%m%d)
        local target="${f%.json}.${stamp}.json.gz"
        if [ -e "$target" ]; then
            # Already archived for that day — drop the duplicate raw file.
            rm -f "$f"
            continue
        fi
        if gzip -c "$f" >"$target" 2>>"$LOG_FILE"; then
            rm -f "$f"
            archived=$((archived + 1))
        fi
    done < <(find "$OUT_DIR" -maxdepth 1 -type f -name '*.json' -mmin "+$age_minutes" -print0 2>/dev/null)

    # Prune old .gz archives.
    while IFS= read -r -d '' f; do
        rm -f "$f" && pruned=$((pruned + 1))
    done < <(find "$OUT_DIR" -maxdepth 1 -type f -name '*.json.gz' -mtime "+$RETENTION_DAYS" -print0 2>/dev/null)

    if [ "$archived" -gt 0 ] || [ "$pruned" -gt 0 ]; then
        log "rotate archived=$archived pruned=$pruned"
    fi
}

main() {
    log "cycle start"
    probe_self
    for h in "${HOSTS[@]}"; do
        probe_one "$h"
    done
    emit_connectivity_row
    rotate_snapshots
    log "cycle end"
}

main "$@"
