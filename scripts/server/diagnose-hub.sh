#!/usr/bin/env bash
# diagnose-hub.sh — 30-second probe chain for "hub is flapping" symptoms.
#
# Walks the same diagnostic chain that took 30 minutes to derive during
# the 2026-04-27 incident, but in parallel and in 30 s:
#
#   1. edge response (HTTP code, latency)
#   2. origin response from PROD_HOST (if SSH-reachable)
#   3. who actually owns the prod port (docker / colima SSH-MUX / autossh)
#   4. is the colima VM being suspended? (lima HostAgent log time-sync events)
#   5. cloudflared tunnel readyConnections + total_requests
#   6. Daphne process is alive in the container
#   7. Django logs show the latest deploy
#
# Each check prints a verdict line. Final summary tells the operator
# which subsystem to drill into. Read-only — no remediation actions.
#
# Usage: ./scripts/server/diagnose-hub.sh [PROD_HOST]   (default: mba)

set -euo pipefail

PROD_HOST="${1:-mba}"
EDGE="https://scitex-lab.scitex-orochi.com/"
ORIGIN_PORT=8559

# Colors only when stdout is a TTY (works in CI and grep both).
if [[ -t 1 ]]; then
    R=$'\033[0;31m'
    G=$'\033[0;32m'
    Y=$'\033[0;33m'
    C=$'\033[0;36m'
    N=$'\033[0m'
else
    R="" G="" Y="" C="" N=""
fi

printf '%sdiagnose-hub %s%s — PROD_HOST=%s%s\n' "$C" "$EDGE" "$N" "$PROD_HOST" ""
echo "------------------------------------------------------------"

verdicts=()

note() { verdicts+=("$1"); }

# 1. edge --------------------------------------------------------------
edge_code=$(curl -s -o /dev/null -m 5 -w "%{http_code}" "$EDGE" 2>/dev/null || echo "000")
edge_t=$(curl -s -o /dev/null -m 5 -w "%{time_total}" "$EDGE" 2>/dev/null || echo "0.0")
case "$edge_code" in
302 | 200)
    printf '%s✓ edge %s in %ss%s\n' "$G" "$edge_code" "$edge_t" "$N"
    ;;
502 | 503 | 530 | 521 | 522 | 524)
    printf '%s✗ edge %s in %ss — Cloudflare can'\''t reach origin%s\n' "$R" "$edge_code" "$edge_t" "$N"
    note "edge returns $edge_code: cloudflared cannot reach origin → check 3,4,5"
    ;;
*)
    printf '%s? edge %s%s\n' "$Y" "$edge_code" "$N"
    note "edge returns unexpected $edge_code"
    ;;
esac

# 2. origin from PROD_HOST ---------------------------------------------
origin=$(ssh -o ConnectTimeout=5 "$PROD_HOST" \
    "curl -s -o /dev/null -m 5 -w '%{http_code} %{time_total}' http://localhost:${ORIGIN_PORT}/ 2>/dev/null" \
    2>/dev/null || echo "000 0")
origin_code=${origin%% *}
origin_t=${origin#* }
case "$origin_code" in
200 | 302)
    if awk "BEGIN{exit !($origin_t > 1.0)}"; then
        printf '%s? origin localhost:%s %s in %ss — slow loopback%s\n' "$Y" "$ORIGIN_PORT" "$origin_code" "$origin_t" "$N"
        note "loopback to origin is slow (>1s) → suspect colima SSH-MUX flap; check 4"
    else
        printf '%s✓ origin localhost:%s %s in %ss%s\n' "$G" "$ORIGIN_PORT" "$origin_code" "$origin_t" "$N"
    fi
    ;;
000)
    printf '%s✗ origin unreachable — SSH to %s failed or port %s dead%s\n' "$R" "$PROD_HOST" "$ORIGIN_PORT" "$N"
    note "origin unreachable: container down or port-bridge gone"
    ;;
*)
    printf '%s✗ origin %s in %ss%s\n' "$R" "$origin_code" "$origin_t" "$N"
    note "origin returns $origin_code"
    ;;
esac

# 3. port-binder identity -----------------------------------------------
binder=$(ssh -o ConnectTimeout=5 "$PROD_HOST" \
    "lsof -nP -iTCP:${ORIGIN_PORT} -sTCP:LISTEN 2>/dev/null | tail -1" \
    2>/dev/null || echo "")
if [[ -z "$binder" ]]; then
    printf '%s? no listener on :%s%s\n' "$Y" "$ORIGIN_PORT" "$N"
    note "no listener on :$ORIGIN_PORT — container or colima down"
elif echo "$binder" | grep -qE "^ssh\b"; then
    printf '%s✓ binder is colima SSH-MUX (expected on macOS+colima)%s\n' "$G" "$N"
elif echo "$binder" | grep -qE "^docker\b"; then
    printf '%s✓ binder is docker (expected on Linux)%s\n' "$G" "$N"
else
    binder_first_token=$(echo "$binder" | awk '{print $1}')
    printf '%s? unexpected binder: %s%s\n' "$Y" "$binder_first_token" "$N"
fi

# 4. lima clock-suspension events --------------------------------------
recent_drift=$(ssh -o ConnectTimeout=5 "$PROD_HOST" \
    'tail -200 ~/.colima/_lima/colima/ha.stderr.log 2>/dev/null | grep -c "Time sync.*adjusted.*-[0-9][0-9][0-9][0-9]"' \
    2>/dev/null || echo "0")
recent_drift=${recent_drift//[^0-9]/}
recent_drift=${recent_drift:-0}
if [[ "$recent_drift" -gt 0 ]]; then
    printf '%s✗ %d clock-jump events in last 200 lima log lines — VM was suspended%s\n' "$R" "$recent_drift" "$N"
    note "macOS suspended the colima VM ($recent_drift clock-jump events); is com.ywatanabe.colima-caffeinate LaunchDaemon loaded? \`launchctl print system/com.ywatanabe.colima-caffeinate\`"
else
    printf '%s✓ no clock-jump events in recent lima log%s\n' "$G" "$N"
fi

# 5. cloudflared tunnel health -----------------------------------------
cf=$(ssh -o ConnectTimeout=5 "$PROD_HOST" \
    "curl -s -m 3 http://127.0.0.1:20241/ready 2>/dev/null" \
    2>/dev/null || echo "")
if echo "$cf" | grep -q '"status":200'; then
    ready=$(echo "$cf" | grep -oE 'readyConnections":[0-9]+' | grep -oE '[0-9]+$')
    total=$(ssh -o ConnectTimeout=5 "$PROD_HOST" \
        "curl -s -m 3 http://127.0.0.1:20241/metrics 2>/dev/null | awk '/^cloudflared_tunnel_total_requests/{print \$2;exit}'" \
        2>/dev/null || echo "?")
    if [[ "$total" == "0" ]]; then
        printf '%s? cloudflared up (%s connections), but total_requests=0 — tunnel registered but not routing the dashboard hostname%s\n' "$Y" "$ready" "$N"
        note "cloudflared has total_requests=0: this connector is standby; check the OTHER tunnel ID — see deployment/README.md §Cloudflare tunnels"
    else
        printf '%s✓ cloudflared up: %s connections, %s total requests%s\n' "$G" "$ready" "$total" "$N"
    fi
else
    printf '%s✗ cloudflared not ready on :20241%s\n' "$R" "$N"
    note "cloudflared metrics endpoint not responding — connector may be down or restarting"
fi

# 6. Daphne process in container ---------------------------------------
# Avoid pgrep (not in slim container PATH); use /proc directly.
daphne=$(ssh -o ConnectTimeout=5 "$PROD_HOST" \
    "PATH=/opt/homebrew/bin:\$PATH; docker exec orochi-server-stable sh -c 'for pid in /proc/[0-9]*; do tr \"\\\\0\" \" \" < \$pid/cmdline 2>/dev/null | grep -l daphne >/dev/null && echo \${pid##*/}; done | head -1' 2>/dev/null" \
    2>/dev/null || echo "")
if [[ -n "$daphne" ]]; then
    printf '%s✓ daphne pid=%s in container%s\n' "$G" "$daphne" "$N"
else
    printf '%s✗ daphne process not found in container%s\n' "$R" "$N"
    note "daphne is dead inside the container — check 'make prod-logs'"
fi

# 7. recent error rate in Django logs ----------------------------------
err_count=$(ssh -o ConnectTimeout=5 "$PROD_HOST" \
    "PATH=/opt/homebrew/bin:\$PATH; docker logs --since=5m orochi-server-stable 2>&1 | grep -ciE 'ERROR|Exception|Traceback'" \
    2>/dev/null || echo "0")
err_count=${err_count//[^0-9]/}
err_count=${err_count:-0}
if [[ "$err_count" -gt 5 ]]; then
    printf '%s✗ %d ERROR/Exception lines in last 5 min Django logs%s\n' "$R" "$err_count" "$N"
    note "Django is logging $err_count errors in 5min — check \`make prod-logs\`"
elif [[ "$err_count" -gt 0 ]]; then
    printf '%s? %d error lines in last 5 min — investigate%s\n' "$Y" "$err_count" "$N"
else
    printf '%s✓ no errors in last 5 min Django logs%s\n' "$G" "$N"
fi

# Summary -----------------------------------------------------------
echo "------------------------------------------------------------"
if [[ ${#verdicts[@]} -eq 0 ]]; then
    printf '%sAll checks passed. If the user is still seeing flap, ask for a%s\n' "$G" "$N"
    printf '%sscreenshot + Ray-ID — the failure may be edge-side (different%s\n' "$G" "$N"
    printf '%sCloudflare PoP than the one this script reaches).%s\n' "$G" "$N"
    exit 0
fi
printf '%s%d issue(s) found:%s\n' "$Y" "${#verdicts[@]}" "$N"
for v in "${verdicts[@]}"; do
    printf '  • %s\n' "$v"
done
exit 1
