#!/usr/bin/env bash
# cloudflared-watchdog.sh — Auto-recover Orochi hub (cloudflared + Daphne).
# Lives in ~/proj/scitex-orochi/deployment/fleet/ (git-tracked).
#
# Install as cron (every 2 min — NOT every minute to avoid restart loops):
#   */2 * * * * ~/proj/scitex-orochi/deployment/fleet/cloudflared-watchdog.sh
#
# Failure modes detected:
#   530/000 → cloudflared tunnel broken → restart cloudflared
#   502 x2  → Daphne stuck → docker restart → if 530 follows, also restart cloudflared

set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Canonical runtime/ layout (dotfiles commit 68bd1592).
_OROCHI_LOG_DIR="${HOME}/.scitex/orochi/runtime/logs"
LOG="${_OROCHI_LOG_DIR}/cloudflared-watchdog.log"
STATE="${_OROCHI_LOG_DIR}/watchdog-state"
mkdir -p "$(dirname "$LOG")"
ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

check() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://scitex-orochi.com/ 2>/dev/null || echo "000"; }

PW=$(decrypt.sh -t mba.ssl 2>/dev/null || echo "")

restart_cloudflared() {
  echo "$(ts) restarting cloudflared" >> "$LOG"
  if [[ -n "$PW" ]]; then
    echo "$PW" | sudo -S killall cloudflared 2>/dev/null || true
    sleep 2
    echo "$PW" | sudo -S launchctl kickstart -kp system/com.cloudflare.cloudflared 2>>"$LOG"
  fi
}

restart_docker() {
  echo "$(ts) restarting orochi-server-stable" >> "$LOG"
  docker restart orochi-server-stable >>"$LOG" 2>&1
}

HTTP_CODE=$(check)

case "$HTTP_CODE" in
  200|302)
    rm -f "$STATE"
    ;;
  530|000)
    echo "$(ts) CRITICAL: HTTP $HTTP_CODE — tunnel broken" >> "$LOG"
    restart_cloudflared
    sleep 5
    VERIFY=$(check)
    echo "$(ts) post-cloudflared-restart: HTTP $VERIFY" >> "$LOG"
    if [[ "$VERIFY" != "200" && "$VERIFY" != "302" ]]; then
      restart_docker
      sleep 8
      restart_cloudflared
      sleep 5
      VERIFY2=$(check)
      echo "$(ts) post-full-restart: HTTP $VERIFY2" >> "$LOG"
    fi
    rm -f "$STATE"
    ;;
  502)
    COUNT=1
    [[ -f "$STATE" ]] && COUNT=$(( $(cat "$STATE") + 1 ))
    echo "$COUNT" > "$STATE"
    echo "$(ts) WARNING: HTTP 502 (consecutive: $COUNT)" >> "$LOG"
    if (( COUNT >= 2 )); then
      restart_docker
      sleep 8
      VERIFY=$(check)
      echo "$(ts) post-docker-restart: HTTP $VERIFY" >> "$LOG"
      if [[ "$VERIFY" == "530" || "$VERIFY" == "000" ]]; then
        restart_cloudflared
        sleep 5
        VERIFY2=$(check)
        echo "$(ts) post-cascade-restart: HTTP $VERIFY2" >> "$LOG"
      fi
      rm -f "$STATE"
    fi
    ;;
  *)
    echo "$(ts) WARNING: HTTP $HTTP_CODE" >> "$LOG"
    ;;
esac
