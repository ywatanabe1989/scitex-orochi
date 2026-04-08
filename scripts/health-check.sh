#!/bin/bash
# -*- coding: utf-8 -*-
# Timestamp: "2026-04-02 (ywatanabe)"
# File: /home/ywatanabe/proj/scitex-orochi/scripts/health-check.sh
# Description: Orochi health checker -- visualizes connection status across all machines

set -uo pipefail

# ──────────────────────────────────────────
# Colors
# ──────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

ok() { printf "  %b%s%b %s\n" "$GREEN" "✓" "$RESET" "$*"; }
fail() { printf "  %b%s%b %s\n" "$RED" "✗" "$RESET" "$*"; }
warn() { printf "  %b%s%b %s\n" "$YELLOW" "?" "$RESET" "$*"; }
section() { printf "\n%b%s%b\n" "$BOLD" "$1" "$RESET"; }
label() { printf "  %b%s%b\n" "$DIM" "$1" "$RESET"; }

SSH_OPTS=(-o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=no -o LogLevel=ERROR)

HOSTS_REACHABLE=0
HOSTS_TOTAL=3
AGENTS_RUNNING=0

# ──────────────────────────────────────────
# Header
# ──────────────────────────────────────────
printf "\n%b" "$BOLD"
printf "═══════════════════════════════════════════\n"
printf "  Orochi Health Check  [%s]\n" "$(date +%Y-%m-%d)"
printf "═══════════════════════════════════════════%b\n" "$RESET"

# ──────────────────────────────────────────
# 1. TELEGRAM
# ──────────────────────────────────────────
section "TELEGRAM"

# 1a. bun process running
TELEGRAM_PID=$(pgrep -f 'bun.*telegram' 2>/dev/null | head -1)
if [[ -n "$TELEGRAM_PID" ]]; then
    ok "Plugin process running (pid $TELEGRAM_PID)"
else
    fail "Plugin process NOT running"
fi

# 1b. Token matches
PLUGIN_ENV_FILE="${TELEGRAM_STATE_DIR:-$HOME/.scitex/agent-container/telegram}/.env"
SECRETS_FILE="$HOME/.bash.d/secrets/010_scitex/01_notification.src"

if [[ -f "$PLUGIN_ENV_FILE" ]] && [[ -f "$SECRETS_FILE" ]]; then
    PLUGIN_TOKEN=$(grep -oP 'TELEGRAM_BOT_TOKEN=\K.*' "$PLUGIN_ENV_FILE" 2>/dev/null)
    # Source secrets to get the env var
    ENV_TOKEN=$(bash -c "source '$SECRETS_FILE' 2>/dev/null && echo \$SCITEX_NOTIFICATION_TELEGRAM_TOKEN")

    if [[ -n "$PLUGIN_TOKEN" ]] && [[ -n "$ENV_TOKEN" ]] && [[ "$PLUGIN_TOKEN" == "$ENV_TOKEN" ]]; then
        ok "Token matches env var"
    elif [[ -z "$PLUGIN_TOKEN" ]]; then
        fail "Token not found in $PLUGIN_ENV_FILE"
    elif [[ -z "$ENV_TOKEN" ]]; then
        fail "Token not found in secrets ($SECRETS_FILE)"
    else
        fail "Token MISMATCH between plugin .env and secrets"
    fi
else
    if [[ ! -f "$PLUGIN_ENV_FILE" ]]; then
        fail "Plugin .env not found: $PLUGIN_ENV_FILE"
    fi
    if [[ ! -f "$SECRETS_FILE" ]]; then
        fail "Secrets file not found: $SECRETS_FILE"
    fi
fi

# 1c. Plugin enabled in settings.json
SETTINGS_FILE="$HOME/.claude/settings.json"
if [[ -f "$SETTINGS_FILE" ]]; then
    if grep -q '"telegram@claude-plugins-official": true' "$SETTINGS_FILE" 2>/dev/null; then
        ok "Plugin enabled in settings.json"
    else
        fail "Plugin NOT enabled in settings.json"
    fi
else
    fail "Settings file not found: $SETTINGS_FILE"
fi

# ──────────────────────────────────────────
# 2. SSH CONNECTIVITY
# ──────────────────────────────────────────
section "SSH CONNECTIVITY"

declare -A SSH_REACHABLE

for host in nas mba spartan; do
    if HOST_INFO=$(timeout 5 ssh "${SSH_OPTS[@]}" "$host" 'hostname; cat /proc/uptime 2>/dev/null || sysctl -n kern.boottime 2>/dev/null' 2>/dev/null) && [[ -n "$HOST_INFO" ]]; then
        HOSTNAME_VAL=$(echo "$HOST_INFO" | head -1)
        UPTIME_RAW=$(echo "$HOST_INFO" | tail -1)
        # Parse uptime from /proc/uptime (Linux: seconds since boot)
        if [[ "$UPTIME_RAW" =~ ^[0-9]+(\.[0-9]+)? ]]; then
            UPTIME_SECS=${UPTIME_RAW%%.*}
            if [[ "$UPTIME_SECS" -ge 86400 ]]; then
                UPTIME_STR="up $((UPTIME_SECS / 86400))d"
            elif [[ "$UPTIME_SECS" -ge 3600 ]]; then
                UPTIME_STR="up $((UPTIME_SECS / 3600))h"
            else
                UPTIME_STR="up $((UPTIME_SECS / 60))m"
            fi
        else
            UPTIME_STR="up"
        fi
        ok "$host ($HOSTNAME_VAL, $UPTIME_STR)"
        SSH_REACHABLE[$host]=1
        HOSTS_REACHABLE=$((HOSTS_REACHABLE + 1))
    else
        fail "$host (unreachable)"
        SSH_REACHABLE[$host]=0
    fi
done

# ──────────────────────────────────────────
# 3. AGENT SCREENS
# ──────────────────────────────────────────
section "AGENTS"

# 3a. Local
label "Local:"
LOCAL_SCREENS=$(screen -ls 2>/dev/null | grep -i 'cld' || true)
if [[ -n "$LOCAL_SCREENS" ]]; then
    while IFS= read -r line; do
        SCREEN_NAME=$(echo "$line" | awk '{print $1}' | sed 's/^[0-9]*\.//')
        SCREEN_STATE=$(echo "$line" | grep -oP '\(([^)]+)\)' | tail -1 | tr -d '()')
        ok "$SCREEN_NAME ($SCREEN_STATE)"
        AGENTS_RUNNING=$((AGENTS_RUNNING + 1))
    done <<<"$LOCAL_SCREENS"
else
    fail "No agent screens"
fi

# 3b. NAS
label "NAS:"
if [[ "${SSH_REACHABLE[nas]:-0}" == "1" ]]; then
    NAS_SCREENS=$(timeout 5 ssh "${SSH_OPTS[@]}" nas 'screen -ls 2>/dev/null' 2>/dev/null | grep -iE 'cld|orochi-agent:' || true)
    if [[ -n "$NAS_SCREENS" ]]; then
        while IFS= read -r line; do
            SCREEN_NAME=$(echo "$line" | awk '{print $1}' | sed 's/^[0-9]*\.//')
            SCREEN_STATE=$(echo "$line" | grep -oP '\(([^)]+)\)' | tail -1 | tr -d '()')
            ok "$SCREEN_NAME ($SCREEN_STATE)"
            AGENTS_RUNNING=$((AGENTS_RUNNING + 1))
        done <<<"$NAS_SCREENS"
    else
        fail "No agent screens"
    fi
else
    warn "Skipped (host unreachable)"
fi

# 3c. Spartan
label "Spartan:"
if [[ "${SSH_REACHABLE[spartan]:-0}" == "1" ]]; then
    SPARTAN_SCREENS=$(timeout 5 ssh "${SSH_OPTS[@]}" spartan 'screen -ls 2>/dev/null' 2>/dev/null | grep -iE 'cld|orochi-agent:' || true)
    if [[ -n "$SPARTAN_SCREENS" ]]; then
        while IFS= read -r line; do
            SCREEN_NAME=$(echo "$line" | awk '{print $1}' | sed 's/^[0-9]*\.//')
            SCREEN_STATE=$(echo "$line" | grep -oP '\(([^)]+)\)' | tail -1 | tr -d '()')
            ok "$SCREEN_NAME ($SCREEN_STATE)"
            AGENTS_RUNNING=$((AGENTS_RUNNING + 1))
        done <<<"$SPARTAN_SCREENS"
    else
        fail "No agent screens"
    fi
else
    warn "Skipped (host unreachable)"
fi

# ──────────────────────────────────────────
# 4. OROCHI INSTANCES (NAS)
# ──────────────────────────────────────────
section "OROCHI INSTANCES (NAS)"

if [[ "${SSH_REACHABLE[nas]:-0}" == "1" ]]; then
    # 4a. Stable instance
    label "Stable (orochi-server-stable):"
    STABLE_CONTAINER=$(timeout 5 ssh "${SSH_OPTS[@]}" nas 'docker ps --filter "name=orochi-server-stable" --format "{{.Names}} (up {{.RunningFor}})" 2>/dev/null' 2>/dev/null || true)
    if [[ -n "$STABLE_CONTAINER" ]]; then
        ok "Container: $STABLE_CONTAINER"
    else
        # Fall back to legacy container name
        LEGACY_CONTAINER=$(timeout 5 ssh "${SSH_OPTS[@]}" nas 'docker ps --filter "name=scitex-orochi" --format "{{.Names}} (up {{.RunningFor}})" 2>/dev/null' 2>/dev/null || true)
        if [[ -n "$LEGACY_CONTAINER" ]]; then
            ok "Container (legacy): $LEGACY_CONTAINER"
        else
            fail "Container NOT running"
        fi
    fi

    DASH_CODE=$(timeout 5 curl -sk -o /dev/null -w "%{http_code}" "https://orochi.scitex.ai" 2>/dev/null || echo "000")
    if [[ "$DASH_CODE" -ge 200 ]] && [[ "$DASH_CODE" -lt 400 ]]; then
        ok "Dashboard https://orochi.scitex.ai ($DASH_CODE)"
    elif [[ "$DASH_CODE" == "000" ]]; then
        fail "Dashboard https://orochi.scitex.ai (timeout/unreachable)"
    else
        fail "Dashboard https://orochi.scitex.ai ($DASH_CODE)"
    fi

    # 4b. Dev instance
    label "Dev (orochi-server-dev):"
    DEV_CONTAINER=$(timeout 5 ssh "${SSH_OPTS[@]}" nas 'docker ps --filter "name=orochi-server-dev" --format "{{.Names}} (up {{.RunningFor}})" 2>/dev/null' 2>/dev/null || true)
    if [[ -n "$DEV_CONTAINER" ]]; then
        ok "Container: $DEV_CONTAINER"
    else
        warn "Container not running (optional)"
    fi

    DEV_DASH_CODE=$(timeout 5 curl -sk -o /dev/null -w "%{http_code}" "https://orochi-dev.scitex.ai" 2>/dev/null || echo "000")
    if [[ "$DEV_DASH_CODE" -ge 200 ]] && [[ "$DEV_DASH_CODE" -lt 400 ]]; then
        ok "Dashboard https://orochi-dev.scitex.ai ($DEV_DASH_CODE)"
    elif [[ "$DEV_DASH_CODE" == "000" ]]; then
        warn "Dashboard https://orochi-dev.scitex.ai (not configured or down)"
    else
        fail "Dashboard https://orochi-dev.scitex.ai ($DEV_DASH_CODE)"
    fi

    # 4c. Telegram bridge on NAS
    label "Telegram bridge:"
    NAS_TELEGRAM=$(timeout 5 ssh "${SSH_OPTS[@]}" nas 'docker ps --format "{{.Names}}" 2>/dev/null' 2>/dev/null | grep -i telegram || true)
    if [[ -n "$NAS_TELEGRAM" ]]; then
        warn "Telegram bridge container on NAS: $NAS_TELEGRAM"
    else
        ok "Telegram bridge DISABLED on NAS"
    fi
else
    warn "NAS unreachable, skipping Orochi checks"
fi

# ──────────────────────────────────────────
# 5. CONFLICTS
# ──────────────────────────────────────────
section "CONFLICTS"

# 5a. Local orochi containers
LOCAL_OROCHI=$(docker ps 2>/dev/null | grep -i orochi || true)
if [[ -n "$LOCAL_OROCHI" ]]; then
    fail "Local orochi container detected: $(echo "$LOCAL_OROCHI" | awk '{print $NF}')"
else
    ok "No local orochi containers"
fi

# 5b. Multiple telegram processes
TELEGRAM_COUNT=$(pgrep -fc 'bun.*telegram' 2>/dev/null || echo "0")
if [[ "$TELEGRAM_COUNT" -le 1 ]]; then
    ok "Single telegram process (count: $TELEGRAM_COUNT)"
else
    fail "Multiple telegram processes (count: $TELEGRAM_COUNT)"
fi

# 5c. Competing pollers on remote hosts
COMPETING=0
for host in nas spartan; do
    if [[ "${SSH_REACHABLE[$host]:-0}" == "1" ]]; then
        REMOTE_POLLERS=$(timeout 5 ssh "${SSH_OPTS[@]}" "$host" 'ps aux 2>/dev/null' 2>/dev/null | grep -i 'telegram.*bot\|telegram.*poll\|bun.*telegram' | grep -v grep || true)
        if [[ -n "$REMOTE_POLLERS" ]]; then
            fail "Competing telegram poller on $host"
            COMPETING=1
        fi
    fi
done
if [[ "$COMPETING" -eq 0 ]]; then
    ok "No competing pollers on remote hosts"
fi

# ──────────────────────────────────────────
# Footer
# ──────────────────────────────────────────
printf "\n%b" "$BOLD"
printf "═══════════════════════════════════════════\n"
printf "  %d/%d hosts reachable  |  %d agent(s) running\n" "$HOSTS_REACHABLE" "$HOSTS_TOTAL" "$AGENTS_RUNNING"
printf "═══════════════════════════════════════════%b\n\n" "$RESET"

# EOF
