#!/usr/bin/env bash
# Runs ON the remote host via `ssh <host> bash -s` with stdin = this script.
# Emits one JSON object on stdout. NO other stdout output allowed.
# Must work on macOS (BSD coreutils) and Linux (GNU coreutils).

set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
host=$(hostname -s 2>/dev/null || hostname)
os=$(uname -s)

# tmux sessions: list of names, or [] if none / tmux missing
if command -v tmux >/dev/null 2>&1; then
    tmux_names=$(tmux list-sessions -F '#{session_name}' 2>/dev/null | sort -u | paste -sd, -)
else
    tmux_names=""
fi
tmux_count=0
if [ -n "$tmux_names" ]; then
    tmux_count=$(printf '%s\n' "$tmux_names" | tr ',' '\n' | grep -c .)
fi

# screen sessions: count of (Detached|Attached) lines
if command -v screen >/dev/null 2>&1; then
    screen_count=$(screen -ls 2>/dev/null | grep -cE '\(Detached\)|\(Attached\)' || true)
else
    screen_count=0
fi

# process counts: pgrep -f then wc -l (BSD pgrep has no -c)
count_proc() {
    local pat="$1"
    pgrep -u "$USER" -f -- "$pat" 2>/dev/null | wc -l | tr -d ' '
}
claude_procs=$(count_proc '(^|/)claude( |$)')
bun_procs=$(count_proc '(^|/)bun ')
node_procs=$(count_proc '(^|/)node ')

# load average (1m)
SYSCTL=/usr/sbin/sysctl
if [ "$os" = "Darwin" ]; then
    load1=$("$SYSCTL" -n vm.loadavg 2>/dev/null | awk '{print $2}')
else
    load1=$(awk '{print $1}' /proc/loadavg 2>/dev/null)
fi
load1=${load1:-0}

# memory used / total (MB), simple cross-OS
mem_total=0
mem_used=0
if [ "$os" = "Darwin" ]; then
    mem_total=$("$SYSCTL" -n hw.memsize 2>/dev/null)
    if [ -n "$mem_total" ] && [ "$mem_total" -gt 0 ] 2>/dev/null; then
        mem_total=$(( mem_total / 1024 / 1024 ))
        # Darwin gotcha: vm_stat "Pages free" alone is always tiny because
        # macOS aggressively uses inactive + speculative pages as cache and
        # reclaims on demand. The true "available" memory is
        # free + inactive + speculative. Treating just "Pages free" as
        # available causes false-positive memory CRITICAL alerts (msg#8603).
        vm_out=$(vm_stat 2>/dev/null)
        page_size=$(printf '%s\n' "$vm_out" | awk '/page size of/ {print $8}')
        page_size=${page_size:-4096}
        pages_free=$(printf '%s\n' "$vm_out" | awk '/Pages free/ {gsub("\\.","",$3); print $3}')
        pages_inactive=$(printf '%s\n' "$vm_out" | awk '/Pages inactive/ {gsub("\\.","",$3); print $3}')
        pages_speculative=$(printf '%s\n' "$vm_out" | awk '/Pages speculative/ {gsub("\\.","",$3); print $3}')
        pages_free=${pages_free:-0}
        pages_inactive=${pages_inactive:-0}
        pages_speculative=${pages_speculative:-0}
        avail_pages=$(( pages_free + pages_inactive + pages_speculative ))
        if [ "$avail_pages" -gt 0 ]; then
            mem_free_mb=$(( avail_pages * page_size / 1024 / 1024 ))
            mem_used=$(( mem_total - mem_free_mb ))
        fi
    else
        mem_total=0
    fi
else
    # `command free` bypasses any shell alias (the dotfiles ship with
    # `alias free='watch -d -n 1 free -h'` for interactive use; that alias
    # would clobber a non-interactive shell-out). Same idea as our /usr/sbin
    # absolute paths for sysctl on Darwin.
    read mem_total mem_used <<<"$(command free -m 2>/dev/null | awk '/^Mem:/ {print $2, $3}')"
fi
mem_total=${mem_total:-0}
mem_used=${mem_used:-0}

# fork pressure: nproc-current vs limit
nproc_cur=$(ps -u "$USER" 2>/dev/null | wc -l | tr -d ' ')
if [ "$os" = "Darwin" ]; then
    nproc_max=$("$SYSCTL" -n kern.maxproc 2>/dev/null || echo 0)
else
    nproc_max=$(cat /proc/sys/kernel/pid_max 2>/dev/null || echo 0)
fi
if [ "${nproc_max:-0}" -gt 0 ]; then
    fork_pressure_pct=$(awk "BEGIN { printf \"%.1f\", ($nproc_cur / $nproc_max) * 100 }")
else
    fork_pressure_pct="null"
fi

# Per-agent context_pct via agent_meta.py if present.
# agent_meta.py reads the live Claude Code session jsonl and emits
# {agent, alive, context_pct, current_tool, last_activity, model, subagents}.
# We call it for each tmux session name and aggregate into agents_meta JSON.
agent_meta_script="$HOME/.scitex/orochi/scripts/agent_meta.py"
agents_meta="{}"
if [ -x "$agent_meta_script" ] && [ -n "$tmux_names" ]; then
    parts=""
    OLD_IFS="$IFS"
    IFS=','
    for name in $tmux_names; do
        [ -z "$name" ] && continue
        meta_line=$("$agent_meta_script" "$name" 2>/dev/null | head -1)
        if [ -n "$meta_line" ] && printf '%s' "$meta_line" | head -c 1 | grep -q '{'; then
            if [ -n "$parts" ]; then
                parts="$parts,\"$name\":$meta_line"
            else
                parts="\"$name\":$meta_line"
            fi
        fi
    done
    IFS="$OLD_IFS"
    if [ -n "$parts" ]; then
        agents_meta="{$parts}"
    fi
fi

# emit JSON (manual to avoid jq dep)
printf '{"ts":"%s","host":"%s","os":"%s","tmux_count":%s,"tmux_names":"%s","screen_count":%s,"claude_procs":%s,"bun_procs":%s,"node_procs":%s,"load1":%s,"mem_total_mb":%s,"mem_used_mb":%s,"nproc_cur":%s,"nproc_max":%s,"fork_pressure_pct":%s,"agents_meta":%s}\n' \
    "$ts" "$host" "$os" "$tmux_count" "$tmux_names" "$screen_count" \
    "$claude_procs" "$bun_procs" "$node_procs" \
    "$load1" "$mem_total" "$mem_used" \
    "$nproc_cur" "$nproc_max" "$fork_pressure_pct" "$agents_meta"
