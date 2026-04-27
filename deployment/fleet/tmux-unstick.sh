#!/usr/bin/env bash
# tmux-unstick.sh — fleet-health-daemon Phase 4 recovery (canonical)
# -----------------------------------------------------------------------------
# Detects and clears two mechanical stuck-agent patterns across every tmux
# pane on the host, without ever sending keys to the pane this script is
# currently running in.
#
# Hot-fix for scitex-orochi#153 (head-spartan msg#11961): the previous POC
# at 478287b lacked both self-exclusion and temporal stability — it would
# sweep its own pane and premature-submit any `[Pasted text …]` marker it
# found even mid-compose. This file is the canonical replacement.
#
# Patterns detected:
#
#   1. paste-buffer-unsent
#      Prompt shows `❯ [Pasted text #N +M lines]` with no subsequent
#      submission. Recovery: `tmux send-keys Enter`.
#
#   2. permission-prompt
#      Claude Code numbered dialog `❯ 1. Yes / 2. Yes, and don't ask
#      again / 3. No`, or the `Do you want to …` variant. Recovery:
#      `tmux send-keys "2" Enter` (option 2 = "yes, and remember").
#
# Safety stack (mandatory, composable):
#
#   A. Self-exclusion — never touch the pane whose `pane_id` matches
#      `$TMUX_PANE`. A script running inside the very pane it would
#      otherwise "recover" is the self-suicide failure mode that hit
#      head-spartan on 2026-04-15 (see issue #153).
#
#   B. Two-sample stability — `[Pasted text #N +M lines]` is a normal
#      live-compose state in Claude Code, not stuck. A single sweep
#      cannot tell "user is typing, paused" from "agent is wedged".
#      We require the SAME tail-hash to appear on two consecutive
#      sweeps (>= TMUX_UNSTICK_STABILITY_SEC, default 120 s) before
#      firing the recovery key. First sighting is recorded-only;
#      second sighting triggers.
#
#   C. Safe-start dry-run window — for the first
#      TMUX_UNSTICK_SAFE_START_SEC seconds after the loop boots, the
#      script runs in --dry-run mode even if DRY_RUN=0. Detections
#      are logged with recovered=false, dry_run=true so the first
#      5 minutes of production output can be eyeballed for
#      false-positives before real keys start firing.
#
#   D. Panic switch — if ~/.scitex/orochi/tmux-unstick.PAUSED exists,
#      the script sleeps without scanning. `touch` the file to halt
#      recovery globally; `rm` to resume.
#
#   E. Per-pane rate limit — after a recovery fires on a pane, that
#      pane is skipped for TMUX_UNSTICK_COOLDOWN_SEC seconds
#      (default 120) so we never spam the same pane repeatedly.
#
#   F. Log-before-act — the detection event is written to NDJSON
#      before `send-keys` is called, so a post-mortem can reconstruct
#      what the script believed even if the send-keys call corrupts
#      subsequent state.
#
# Usage:
#
#   bash tmux-unstick.sh [--once|--loop|--dry-run-once]
#
#     --once           single sweep, exit (default)
#     --loop           sweep every INTERVAL seconds until killed
#     --dry-run-once   single sweep, never sends keys
#     -h, --help       print usage
#
# Environment overrides:
#
#   TMUX_UNSTICK_LOG              NDJSON log path (default
#                                  ~/.scitex/orochi/logs/tmux-unstick.ndjson)
#   TMUX_UNSTICK_INTERVAL_SEC     seconds between sweeps in --loop mode
#                                  (default 60)
#   TMUX_UNSTICK_STABILITY_SEC    per-pane minimum age of a stable
#                                  match before firing (default 120)
#   TMUX_UNSTICK_COOLDOWN_SEC     per-pane silence after a recovery
#                                  fires (default 120)
#   TMUX_UNSTICK_SAFE_START_SEC   initial dry-run window on loop boot
#                                  (default 300 = 5 min)
#   TMUX_UNSTICK_HEARTBEAT_EVERY  emit a meta heartbeat every N sweeps
#                                  in --loop mode (default 5)
#   TMUX_UNSTICK_STATE_DIR        per-pane stability snapshot dir
#                                  (default ~/.scitex/orochi/tmux-unstick-state/)
#   TMUX_UNSTICK_PAUSE_FILE       panic-switch marker file (default
#                                  ~/.scitex/orochi/tmux-unstick.PAUSED)
#   DRY_RUN                       if 1, detect and log but never send
#                                  keys (default 0; overridden to 1
#                                  during the safe-start window)
#
# Schema orochi_version: scitex-orochi/tmux-unstick/v2 (bumped from v1 POC).
# -----------------------------------------------------------------------------

set -u
set -o pipefail

SCHEMA="scitex-orochi/tmux-unstick/v2"
LOG="${TMUX_UNSTICK_LOG:-$HOME/.scitex/orochi/logs/tmux-unstick.ndjson}"
INTERVAL="${TMUX_UNSTICK_INTERVAL_SEC:-60}"
STABILITY_SEC="${TMUX_UNSTICK_STABILITY_SEC:-120}"
COOLDOWN_SEC="${TMUX_UNSTICK_COOLDOWN_SEC:-120}"
SAFE_START_SEC="${TMUX_UNSTICK_SAFE_START_SEC:-300}"
HEARTBEAT_EVERY="${TMUX_UNSTICK_HEARTBEAT_EVERY:-5}"
STATE_DIR="${TMUX_UNSTICK_STATE_DIR:-$HOME/.scitex/orochi/tmux-unstick-state}"
PAUSE_FILE="${TMUX_UNSTICK_PAUSE_FILE:-$HOME/.scitex/orochi/tmux-unstick.PAUSED}"
DRY_RUN_ENV="${DRY_RUN:-0}"
MODE="${1:---once}"
# Shorthand promotion
if [[ "$MODE" == "--dry-run-once" ]]; then
  MODE="--once"
  DRY_RUN_ENV=1
fi

SELF_PANE_ID="${TMUX_PANE:-}"
HOST="$(orochi_hostname -s)"
BOOT_EPOCH="$(date +%s)"

mkdir -p "$(dirname "$LOG")" "$STATE_DIR"

iso_ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

if ! command -v python3 >/dev/null 2>&1; then
  echo "tmux-unstick: python3 not on PATH, refusing to run" >&2
  exit 3
fi

json_escape() {
  python3 -c 'import json, sys; sys.stdout.write(json.dumps(sys.stdin.read()))'
}

hash_tail() {
  if command -v sha1sum >/dev/null 2>&1; then
    sha1sum | awk '{print $1}'
  else
    cksum | awk '{print $1}'
  fi
}

safe_name() {
  printf '%s' "$1" | tr -c 'a-zA-Z0-9_-' '_'
}

emit() {
  # emit <event> <session_addr> <pane_id> <recovered_bool|null> <dry_run_bool> <detail_json>
  local event="$1" session="$2" pane_id="$3" recovered="$4" dry_run="$5" detail="$6"
  printf '{"schema":"%s","host":"%s","ts":"%s","event":"%s","session":%s,"pane_id":%s,"recovered":%s,"dry_run":%s,"detail":%s}\n' \
    "$SCHEMA" "$HOST" "$(iso_ts)" "$event" \
    "$(printf '%s' "$session" | json_escape)" \
    "$(printf '%s' "$pane_id" | json_escape)" \
    "$recovered" "$dry_run" "$detail" >> "$LOG"
}

detect_paste_buffer_unsent() {
  grep -qE '^[[:space:]]*❯.*\[Pasted text #[0-9]+ \+[0-9]+ lines?\]'
}

detect_permission_prompt() {
  grep -qE '(Do you want to (proceed|create|make this edit|allow))|(^[[:space:]]*❯?[[:space:]]*1\.[[:space:]]*Yes)'
}

is_in_safe_start_window() {
  local now age
  now="$(date +%s)"
  age=$(( now - BOOT_EPOCH ))
  (( age < SAFE_START_SEC ))
}

is_paused() { [[ -f "$PAUSE_FILE" ]]; }

sweep_once() {
  local total=0 skipped_self=0
  local detected_paste=0 detected_perm=0 recovered=0 in_cooldown=0 first_sighting=0

  if is_paused; then
    emit "sweep-paused" "__sweep__" "" "null" "false" \
      "{\"reason\":\"panic-switch\",\"pause_file\":$(printf '%s' "$PAUSE_FILE" | json_escape)}"
    return 0
  fi

  local effective_dry_run="$DRY_RUN_ENV"
  if [[ "$MODE" == "--loop" ]] && is_in_safe_start_window; then
    effective_dry_run=1
  fi

  while IFS='|' read -r pane_id session_addr; do
    [[ -z "$pane_id" ]] && continue
    total=$(( total + 1 ))

    # Safety A: self-exclusion
    if [[ -n "$SELF_PANE_ID" && "$pane_id" == "$SELF_PANE_ID" ]]; then
      skipped_self=$(( skipped_self + 1 ))
      continue
    fi

    local safe stamp_pat stamp_hash stamp_cool
    safe="$(safe_name "$pane_id")"
    stamp_pat="$STATE_DIR/${safe}.pattern"
    stamp_hash="$STATE_DIR/${safe}.hash"
    stamp_cool="$STATE_DIR/${safe}.cooldown"

    # Safety E: per-pane cooldown after a recent recovery
    if [[ -f "$stamp_cool" ]]; then
      local age=$(( $(date +%s) - $(stat -c %Y "$stamp_cool" 2>/dev/null || echo 0) ))
      if (( age < COOLDOWN_SEC )); then
        in_cooldown=$(( in_cooldown + 1 ))
        continue
      else
        rm -f "$stamp_cool"
      fi
    fi

    local tail_txt tail_hash
    tail_txt="$(tmux capture-pane -p -S -20 -t "$pane_id" 2>/dev/null || true)"
    [[ -z "$tail_txt" ]] && continue
    tail_hash="$(printf '%s' "$tail_txt" | hash_tail)"

    local pattern=""
    if printf '%s' "$tail_txt" | detect_permission_prompt; then
      pattern="permission-prompt"
      detected_perm=$(( detected_perm + 1 ))
    elif printf '%s' "$tail_txt" | detect_paste_buffer_unsent; then
      pattern="paste-buffer-unsent"
      detected_paste=$(( detected_paste + 1 ))
    else
      rm -f "$stamp_pat" "$stamp_hash" 2>/dev/null || true
      continue
    fi

    # Safety B: two-sample stability check.
    #
    # Require the SAME (pattern, tail_hash) to be observed across two
    # sweeps at least STABILITY_SEC seconds apart before firing the
    # recovery action.
    #
    # Critical correctness rule: when the current observation matches
    # the prior stamp (same pattern AND same hash), DO NOT touch the
    # stamp files — preserve their mtime so the next sweep can compute
    # an accurate `prior_age`. Only write/replace the stamp files when
    # transitioning from "no prior" or "different prior" to the
    # current pattern. Re-writing on every sweep was the v2.0 bug
    # (scitex-orochi#155): mtime kept resetting, prior_age stayed
    # ~INTERVAL_SEC, never reached STABILITY_SEC, so first-sighting
    # never graduated to stable-match — recovery never fired.
    local prior_pattern="" prior_hash="" prior_age=0 stable=0 same_as_prior=0
    if [[ -f "$stamp_pat" && -f "$stamp_hash" ]]; then
      prior_pattern="$(cat "$stamp_pat" 2>/dev/null || true)"
      prior_hash="$(cat "$stamp_hash" 2>/dev/null || true)"
      prior_age=$(( $(date +%s) - $(stat -c %Y "$stamp_hash" 2>/dev/null || echo 0) ))
      if [[ "$prior_pattern" == "$pattern" && "$prior_hash" == "$tail_hash" ]]; then
        same_as_prior=1
        if (( prior_age >= STABILITY_SEC )); then
          stable=1
        fi
      fi
    fi

    if (( stable == 0 )); then
      first_sighting=$(( first_sighting + 1 ))
      # Only refresh the stamp files when the observation is NEW or
      # CHANGED. Preserving mtime on identical observations is what
      # makes Safety B actually work — see scitex-orochi#155.
      if (( same_as_prior == 0 )); then
        printf '%s' "$pattern" > "$stamp_pat"
        printf '%s' "$tail_hash" > "$stamp_hash"
      fi
      local snip_json
      snip_json="$(printf '%s' "$tail_txt" | tail -6 | json_escape)"
      emit "first-sighting" "$session_addr" "$pane_id" "false" "true" \
        "{\"pattern\":$(printf '%s' "$pattern" | json_escape),\"snippet\":$snip_json,\"tail_hash\":$(printf '%s' "$tail_hash" | json_escape),\"stability_sec_required\":$STABILITY_SEC,\"prior_age\":$prior_age,\"same_as_prior\":$same_as_prior}"
      continue
    fi

    local snip_json
    snip_json="$(printf '%s' "$tail_txt" | tail -6 | json_escape)"
    local action
    if [[ "$pattern" == "paste-buffer-unsent" ]]; then
      action="send-keys Enter"
    else
      action="send-keys '2' Enter"
    fi

    # Safety F: log-before-act
    if [[ "$effective_dry_run" == "1" ]]; then
      emit "stable-match" "$session_addr" "$pane_id" "false" "true" \
        "{\"pattern\":$(printf '%s' "$pattern" | json_escape),\"snippet\":$snip_json,\"action\":$(printf '%s' "$action" | json_escape),\"skipped_reason\":\"dry_run\"}"
      continue
    fi

    emit "stable-match" "$session_addr" "$pane_id" "null" "false" \
      "{\"pattern\":$(printf '%s' "$pattern" | json_escape),\"snippet\":$snip_json,\"action\":$(printf '%s' "$action" | json_escape),\"about_to_fire\":true}"

    local fire_ok=1
    case "$pattern" in
      paste-buffer-unsent)
        tmux send-keys -t "$pane_id" Enter 2>/dev/null || fire_ok=0
        ;;
      permission-prompt)
        tmux send-keys -t "$pane_id" "2" 2>/dev/null || fire_ok=0
        tmux send-keys -t "$pane_id" Enter 2>/dev/null || fire_ok=0
        ;;
    esac

    if (( fire_ok == 1 )); then
      recovered=$(( recovered + 1 ))
      touch "$stamp_cool"
      rm -f "$stamp_pat" "$stamp_hash"
      emit "fired" "$session_addr" "$pane_id" "true" "false" \
        "{\"pattern\":$(printf '%s' "$pattern" | json_escape),\"action\":$(printf '%s' "$action" | json_escape)}"
    else
      emit "fire-failed" "$session_addr" "$pane_id" "false" "false" \
        "{\"pattern\":$(printf '%s' "$pattern" | json_escape),\"action\":$(printf '%s' "$action" | json_escape)}"
    fi
  done < <(tmux list-panes -a -F '#{pane_id}|#{session_name}:#{window_index}.#{pane_index}' 2>/dev/null)

  emit "sweep-summary" "__sweep__" "" "null" "$effective_dry_run" \
    "{\"total\":$total,\"skipped_self\":$skipped_self,\"in_cooldown\":$in_cooldown,\"first_sighting\":$first_sighting,\"detected_paste\":$detected_paste,\"detected_perm\":$detected_perm,\"recovered\":$recovered,\"safe_start\":$(is_in_safe_start_window && echo true || echo false)}"
}

print_usage() {
  cat <<EOF
usage: $(basename "$0") [--once|--loop|--dry-run-once|--help]
  --once            run one sweep and exit (default)
  --loop            run every TMUX_UNSTICK_INTERVAL_SEC seconds until killed
  --dry-run-once    run one sweep in dry-run mode
  -h, --help        print this usage

Environment: see header of tmux-unstick.sh for full list.
EOF
}

case "$MODE" in
  --once)
    sweep_once
    ;;
  --loop)
    emit "loop-start" "__sweep__" "" "null" "false" \
      "{\"pid\":$$,\"interval_sec\":$INTERVAL,\"stability_sec\":$STABILITY_SEC,\"safe_start_sec\":$SAFE_START_SEC,\"self_pane\":$(printf '%s' "$SELF_PANE_ID" | json_escape)}"
    tick=0
    while true; do
      sweep_once || true
      tick=$(( tick + 1 ))
      if (( HEARTBEAT_EVERY > 0 && tick % HEARTBEAT_EVERY == 0 )); then
        n_panes=$(tmux list-panes -a 2>/dev/null | wc -l)
        emit "heartbeat" "__sweep__" "" "null" "false" \
          "{\"pid\":$$,\"tick\":$tick,\"n_panes\":$n_panes}"
      fi
      sleep "$INTERVAL"
    done
    ;;
  -h|--help)
    print_usage
    ;;
  *)
    echo "unknown option: $MODE" >&2
    print_usage >&2
    exit 2
    ;;
esac
