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

AGENTS_DIR="${SCITEX_OROCHI_AGENTS_DIR:-$HOME/.scitex/orochi/agents}"
WORKSPACES_DIR="${SCITEX_OROCHI_WORKSPACES_DIR:-$HOME/.scitex/orochi/workspaces}"

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
    local agent_dir="$AGENTS_DIR/$agent_name"
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
    for agent_dir in "$AGENTS_DIR"/*/; do
        agent_name="$(basename "$agent_dir")"
        [[ "$agent_name" == "legacy" ]] && continue
        if [[ -f "$agent_dir/.mcp.json.example" ]]; then
            setup_agent "$agent_name"
            count=$((count + 1))
        fi
    done
    printf "done: %d agent(s) processed\n" "$count"
else
    setup_agent "$1"
fi

# EOF
