#!/usr/bin/env bash
# tmux-unstick-poc.sh — fleet-health-daemon Phase 4 recovery POC
# -----------------------------------------------------------------------------
# POC for the "paste-buffer-unsent" + "permission-prompt" tmux stuck-agent
# recovery pattern. Authored by head-mba 2026-04-15 as input for the
# skill-manager fleet-health-daemon design doc (todo#146 rewrite).
#
# Scope:
#   - MBA tmux sessions only (launchd or bare loop wrapper)
#   - Read-only capture + targeted send-keys unstick
#   - NDJSON log of every detection + recovery event
#   - Idempotent (re-sending Enter to an already-empty prompt is harmless)
#
# What it detects:
#   1. paste-buffer-unsent: pane prompt shows "[Pasted text #N +M lines]"
#      with no subsequent submission. Trigger: send Enter.
#   2. permission-prompt: pane shows "Do you want to proceed?" or
#      "❯ 1. Yes / 2. ... / 3. No" menu. Trigger: send "2" + Enter
#      (option 2 = "always allow" when available, otherwise "Yes").
#
# What it does NOT do:
#   - extra-usage wedge recovery (needs /exit + relaunch, session-loss)
#   - tmux session kill/respawn (destructive, human-action required)
#   - MCP zombie dedup (requires ps grep, out of scope for POC)
#   - cross-host probe (MBA-only, other hosts need their own copy)
#
# Usage:
#   bash ~/.scitex/orochi/scripts/tmux-unstick-poc.sh [--once|--loop]
#
#   --once: run one sweep and exit (default)
#   --loop: run every $INTERVAL seconds until killed (default 60)
#
# Environment:
#   INTERVAL: seconds between sweeps in --loop mode (default 60)
#   LOG_FILE: NDJSON output path (default ~/.scitex/orochi/logs/tmux-unstick-poc.ndjson)
#   DRY_RUN:  if set to 1, detect and log but do NOT send any keys
# -----------------------------------------------------------------------------

set -euo pipefail

INTERVAL="${INTERVAL:-60}"
LOG_FILE="${LOG_FILE:-$HOME/.scitex/orochi/logs/tmux-unstick-poc.ndjson}"
DRY_RUN="${DRY_RUN:-0}"
MODE="${1:---once}"

mkdir -p "$(dirname "$LOG_FILE")"

iso_ts() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

# json_escape stdin into a JSON-safe string literal (including surrounding quotes)
json_escape() {
  python3 -c 'import json, sys; sys.stdout.write(json.dumps(sys.stdin.read()))'
}

emit() {
  # emit <session> <event_kind> <recovered_bool> <detail_json>
  local session="$1" kind="$2" recovered="$3" detail="$4"
  printf '{"schema":"scitex-orochi/tmux-unstick-poc/v1","host":"%s","ts":"%s","session":"%s","event":"%s","recovered":%s,"detail":%s}\n' \
    "$(hostname -s)" "$(iso_ts)" "$session" "$kind" "$recovered" "$detail" >> "$LOG_FILE"
}

# Capture last N lines of a pane, suppressing errors if the session vanished
capture_pane() {
  local session="$1"
  tmux capture-pane -p -S -20 -t "$session" 2>/dev/null || true
}

# Detect pattern 1: paste-buffer-unsent
# Signature: prompt line contains "[Pasted text #N +M lines]"
# NDJSON detail: the matched prompt snippet
detect_paste_buffer_unsent() {
  local tail="$1"
  # Match lines like:  ❯ [Pasted text #1 +5 lines]...
  # or combinations like [Pasted text #1 +4 lines][Pasted text #2 +5 lines]
  if grep -qE '^\s*❯.*\[Pasted text #[0-9]+ \+[0-9]+ lines?\]' <<<"$tail"; then
    return 0
  fi
  return 1
}

# Detect pattern 2: permission-prompt (numbered menu)
# Signature: line containing "Do you want to" or menu like "1. Yes / 2. ... / 3. No"
detect_permission_prompt() {
  local tail="$1"
  if grep -qE '(Do you want to (proceed|create|make this edit|allow))|(^\s*❯?\s*1\.\s*Yes)' <<<"$tail"; then
    return 0
  fi
  return 1
}

# Sweep all sessions once
sweep_once() {
  local session tail recovered kind
  local total_panes=0 detected=0 recovered_count=0

  while IFS= read -r session; do
    [[ -z "$session" ]] && continue
    total_panes=$((total_panes+1))

    tail="$(capture_pane "$session")"
    [[ -z "$tail" ]] && continue

    if detect_permission_prompt "$tail"; then
      detected=$((detected+1))
      kind="permission-prompt"
      local snippet_json
      snippet_json="$(printf '%s' "$tail" | tail -6 | json_escape)"

      if [[ "$DRY_RUN" == "1" ]]; then
        emit "$session" "$kind" false "{\"snippet\":$snippet_json,\"dry_run\":true}"
      else
        if tmux send-keys -t "$session" "2" Enter 2>/dev/null; then
          emit "$session" "$kind" true "{\"snippet\":$snippet_json,\"action\":\"send-keys '2' Enter\"}"
          recovered_count=$((recovered_count+1))
        else
          emit "$session" "$kind" false "{\"snippet\":$snippet_json,\"error\":\"send-keys failed\"}"
        fi
      fi
      continue
    fi

    if detect_paste_buffer_unsent "$tail"; then
      detected=$((detected+1))
      kind="paste-buffer-unsent"
      local snippet_json
      snippet_json="$(printf '%s' "$tail" | tail -6 | json_escape)"

      if [[ "$DRY_RUN" == "1" ]]; then
        emit "$session" "$kind" false "{\"snippet\":$snippet_json,\"dry_run\":true}"
      else
        if tmux send-keys -t "$session" Enter 2>/dev/null; then
          emit "$session" "$kind" true "{\"snippet\":$snippet_json,\"action\":\"send-keys Enter\"}"
          recovered_count=$((recovered_count+1))
        else
          emit "$session" "$kind" false "{\"snippet\":$snippet_json,\"error\":\"send-keys failed\"}"
        fi
      fi
      continue
    fi
  done < <(tmux ls -F '#{session_name}' 2>/dev/null)

  # Summary event per sweep
  emit "__sweep__" "sweep-summary" "null" \
    "{\"total_panes\":$total_panes,\"detected\":$detected,\"recovered\":$recovered_count,\"mode\":\"${MODE#--}\",\"dry_run\":$([[ \"$DRY_RUN\" == \"1\" ]] && echo true || echo false)}"

  printf '[tmux-unstick-poc] sweep: total=%d detected=%d recovered=%d\n' \
    "$total_panes" "$detected" "$recovered_count" >&2
}

# Entrypoint
case "$MODE" in
  --once)
    sweep_once
    ;;
  --loop)
    while true; do
      sweep_once
      sleep "$INTERVAL"
    done
    ;;
  *)
    echo "usage: $0 [--once|--loop]" >&2
    exit 2
    ;;
esac
