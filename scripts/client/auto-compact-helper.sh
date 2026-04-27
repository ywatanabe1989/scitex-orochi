#!/usr/bin/env bash
# auto-compact-helper.sh — bash helper for the agent-self-compact protocol
# (todo#446 actuator MVP, paired with auto-compact-protocol.md skill)
# ---------------------------------------------------------------------------
# Reads the calling agent's own context-% from the Claude Code statusline
# buffer (per CLAUDE.md section 8) and prints a JSON summary that an
# agent's /loop body can parse to decide whether to schedule
# `mcp__scitex-orochi__self_command command="/compact"`.
#
# This script does NOT call MCP itself — MCP tools are accessible only
# from inside the agent's Claude Code conversation. The agent invokes
# this script from its tmux/bash side, reads the JSON, and (if context
# is over threshold) calls the MCP tool from its own conversation.
#
# Usage (in an agent's /loop body):
#   read CTX_JSON < <(bash ~/.dotfiles/src/.scitex/orochi/scripts/auto-compact-helper.sh)
#   # parse CTX_JSON.orochi_context_pct, decide, then if over threshold:
#   #   mcp__scitex-orochi__self_command command="/compact" delay_ms=3000
#
# Env vars:
#   AGENT_NAME        — defaults to $SCITEX_OROCHI_AGENT
#   STATUSLINE_BUFFER — defaults to "*scitex-orochi-buffer-${AGENT_NAME}*"
#                       (matches the emacs-vterm buffer naming pattern
#                        used by the fleet today)
# ---------------------------------------------------------------------------

set -euo pipefail

AGENT_NAME="${AGENT_NAME:-${SCITEX_OROCHI_AGENT:-unknown}}"
STATUSLINE_BUFFER="${STATUSLINE_BUFFER:-*scitex-orochi-buffer-${AGENT_NAME}*}"

# Try emacsclient first (canonical, per CLAUDE.md section 8).
read_via_emacs() {
    if ! command -v emacsclient >/dev/null 2>&1; then
        return 1
    fi
    emacsclient -e \
        "(with-current-buffer \"${STATUSLINE_BUFFER}\" \
            (buffer-substring-no-properties \
                (max (- (point-max) 500) (point-min)) (point-max)))" \
        2>/dev/null || return 1
}

# Fallback: try reading the agent's own tmux pane directly via tmux
# capture-pane. This works when the agent is running inside a tmux
# session named exactly $AGENT_NAME (the canonical pattern).
read_via_tmux() {
    if ! command -v tmux >/dev/null 2>&1; then
        return 1
    fi
    tmux capture-pane -pt "${AGENT_NAME}" 2>/dev/null | tail -20 || return 1
}

# Parse "Context left: 36%" or "Context: XX%" or similar statusline forms.
# Returns the integer percent of context REMAINING (Claude statusline shows
# remaining, not consumed). Falls back to empty string on parse failure.
extract_orochi_context_pct() {
    local text="$1"
    # Try several known statusline patterns in order of specificity.
    # Pattern 1: "Context left: NN%"
    local pct
    pct=$(printf '%s' "$text" | grep -oE 'Context left: [0-9]+%' | tail -1 | grep -oE '[0-9]+')
    if [[ -n "$pct" ]]; then printf '%s' "$pct"; return 0; fi
    # Pattern 2: "Context: NN%"
    pct=$(printf '%s' "$text" | grep -oE 'Context: [0-9]+%' | tail -1 | grep -oE '[0-9]+')
    if [[ -n "$pct" ]]; then printf '%s' "$pct"; return 0; fi
    # Pattern 3: bare "NN% context"
    pct=$(printf '%s' "$text" | grep -oE '[0-9]+% context' | tail -1 | grep -oE '[0-9]+')
    if [[ -n "$pct" ]]; then printf '%s' "$pct"; return 0; fi
    return 1
}

main() {
    local raw=""
    local source="none"
    if raw=$(read_via_emacs 2>/dev/null) && [[ -n "$raw" ]]; then
        source="emacs"
    elif raw=$(read_via_tmux 2>/dev/null) && [[ -n "$raw" ]]; then
        source="tmux"
    fi

    local pct=""
    if [[ -n "$raw" ]]; then
        pct=$(extract_orochi_context_pct "$raw" || true)
    fi

    # Emit JSON: agent / orochi_context_pct_remaining (null if unknown) / source
    if [[ -n "$pct" ]]; then
        printf '{"agent":"%s","orochi_context_pct_remaining":%s,"source":"%s","ts":"%s"}\n' \
            "$AGENT_NAME" "$pct" "$source" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    else
        printf '{"agent":"%s","orochi_context_pct_remaining":null,"source":"%s","ts":"%s"}\n' \
            "$AGENT_NAME" "$source" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    fi
}

main "$@"
