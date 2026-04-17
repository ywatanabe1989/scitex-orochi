#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Timestamp: "2026-04-11 (ywatanabe)"
# File: /home/ywatanabe/proj/scitex-orochi/scripts/setup-workspace.sh
# Description: Expand env vars in .mcp.json.example and deploy to workspace
#
# Usage: setup-workspace.sh <agent-name> [--all]
#   setup-workspace.sh head-ywata-note-win   # single agent
#   setup-workspace.sh --all                 # all agents with .mcp.json.example

set -euo pipefail

# Canonical post-68bd1592 layout:
#   agent defs  → shared/agents/<name>/ or <host>/agents/<name>/
#   workspaces  → runtime/workspaces/<name>/
# Legacy flat ~/.scitex/orochi/{agents,workspaces}/ are honoured as a
# fallback when the runtime/ skeleton hasn't been bootstrapped yet.
# DEPRECATED: drop the legacy fallbacks after rollout.
_OROCHI_ROOT="$HOME/.scitex/orochi"
# Ordered list of agent-definition roots. Host override wins, shared next,
# legacy last. Callers that override via SCITEX_OROCHI_AGENTS_DIR bypass
# the entire search.
_HOST_FOR_AGENTS="${SCITEX_OROCHI_HOSTNAME:-$(hostname -s 2>/dev/null || hostname)}"
_DEFAULT_AGENT_DIRS=(
    "$_OROCHI_ROOT/$_HOST_FOR_AGENTS/agents"
    "$_OROCHI_ROOT/shared/agents"
    "$_OROCHI_ROOT/agents"
)
# Back-compat: AGENTS_DIR is still a single path (first usable root). Most
# consumers just want "one place to start looking".
_first_existing_agents_dir() {
    local d
    for d in "${_DEFAULT_AGENT_DIRS[@]}"; do
        if [[ -d "$d" ]]; then
            printf '%s' "$d"
            return
        fi
    done
    # Fall back to the canonical shared/agents/ path so error messages
    # point users to the correct, expected location.
    printf '%s' "$_OROCHI_ROOT/shared/agents"
}
AGENTS_DIR="${SCITEX_OROCHI_AGENTS_DIR:-$(_first_existing_agents_dir)}"
_default_workspaces_dir() {
    if [[ -d "$_OROCHI_ROOT/runtime" ]]; then
        printf '%s' "$_OROCHI_ROOT/runtime/workspaces"
    elif [[ -d "$_OROCHI_ROOT/workspaces" ]]; then
        printf '%s' "$_OROCHI_ROOT/workspaces"
    else
        printf '%s' "$_OROCHI_ROOT/runtime/workspaces"
    fi
}
WORKSPACES_DIR="${SCITEX_OROCHI_WORKSPACES_DIR:-$(_default_workspaces_dir)}"

# Resolve an agent dir by name across all canonical roots. Echoes the
# first match on stdout. Falls back to the default AGENTS_DIR/<name> so
# callers get a consistent "not found" error path.
_resolve_agent_dir() {
    local name="$1" d candidate
    for d in "${_DEFAULT_AGENT_DIRS[@]}"; do
        candidate="$d/$name"
        if [[ -d "$candidate" ]]; then
            printf '%s' "$candidate"
            return
        fi
    done
    printf '%s' "$AGENTS_DIR/$name"
}

# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

die() { printf "error: %s\n" "$1" >&2; exit 1; }

resolve_bun() {
    # Claude Code's MCP spawner doesn't use a login shell, so PATH-based
    # "bun" won't resolve. Find the absolute path.
    local bun_path
    bun_path="${BUN_PATH:-}"
    [[ -n "$bun_path" && -x "$bun_path" ]] && { echo "$bun_path"; return; }

    bun_path="$(command -v bun 2>/dev/null || true)"
    [[ -n "$bun_path" ]] && { echo "$bun_path"; return; }

    bun_path="$HOME/.bun/bin/bun"
    [[ -x "$bun_path" ]] && { echo "$bun_path"; return; }

    die "bun not found. Set BUN_PATH or install bun."
}

expand_env_vars() {
    # Expand $VAR and ${VAR} references in stdin using envsubst if available,
    # otherwise fall back to a perl one-liner.
    if command -v envsubst &>/dev/null; then
        envsubst
    else
        perl -pe 's/\$\{(\w+)\}|\$(\w+)/$ENV{$1||$2}\/\/""}/ge'
    fi
}

setup_agent() {
    local agent_name="$1"
    local agent_dir
    agent_dir="$(_resolve_agent_dir "$agent_name")"
    local workspace_dir="$WORKSPACES_DIR/$agent_name"
    local example="$agent_dir/.mcp.json.example"

    # Validate
    [[ -d "$agent_dir" ]] || die "agent dir not found: $agent_dir"
    [[ -f "$example" ]]   || { printf "skip: %s (no .mcp.json.example)\n" "$agent_name"; return 0; }

    # Create workspace
    mkdir -p "$workspace_dir"

    # Resolve bun to absolute path
    local bun_abs
    bun_abs="$(resolve_bun)"

    # Expand env vars and replace bare "bun" command with absolute path.
    # The sed replacement is careful to only match the "command" field value,
    # not occurrences inside paths like ".bun/bin/bun".
    expand_env_vars < "$example" \
        | sed "s|\"command\": *\"bun\"|\"command\": \"${bun_abs}\"|" \
        > "$workspace_dir/.mcp.json"

    printf "ok: %s -> %s/.mcp.json\n" "$example" "$workspace_dir"

    # Copy CLAUDE.md if present in agent dir
    if [[ -f "$agent_dir/CLAUDE.md" ]]; then
        cp "$agent_dir/CLAUDE.md" "$workspace_dir/CLAUDE.md"
        printf "ok: copied CLAUDE.md -> %s/\n" "$workspace_dir"
    fi
}

# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

if [[ $# -lt 1 ]]; then
    printf "usage: %s <agent-name> | --all\n" "$(basename "$0")"
    exit 1
fi

if [[ "$1" == "--all" ]]; then
    count=0
    declare -A _seen_all=()
    for root in "${_DEFAULT_AGENT_DIRS[@]}"; do
        [[ -d "$root" ]] || continue
        for agent_dir in "$root"/*/; do
            [[ -d "$agent_dir" ]] || continue
            agent_name="$(basename "$agent_dir")"
            case "$agent_name" in
                legacy|legacy-agents|_*) continue ;;
            esac
            # Skip duplicates across roots (host override wins).
            if [[ -n "${_seen_all[$agent_name]:-}" ]]; then
                continue
            fi
            _seen_all[$agent_name]=1
            if [[ -f "$agent_dir/.mcp.json.example" ]]; then
                setup_agent "$agent_name"
                count=$((count + 1))
            fi
        done
    done
    printf "done: %d agent(s) processed\n" "$count"
else
    setup_agent "$1"
fi

# EOF
