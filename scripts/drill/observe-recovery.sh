#!/usr/bin/env bash
# observe-recovery.sh — single-screen view of the recovery markers
# the operator needs to see during a hub-restart drill (FR-K + FR-L1
# + FR-M + FR-N validate-in-one-window per lead msg#23363).
#
# Usage:
#   scripts/drill/observe-recovery.sh [--sidecar-log PATH] [--auditor-log PATH] [--stale-pr-log PATH]
#
# Default log paths assume the standard sac-managed agent layout:
#   ~/.scitex/orochi/runtime/logs/<agent-name>.log
# and the standard daemon log dir:
#   ~/.scitex/orochi/daemon-logs/<daemon-name>.log
#
# What the script does:
#   * tails each known recovery-relevant log concurrently
#   * highlights the marker lines the drill checklist looks for
#   * prefixes each line with its source so 4 streams in one pane
#     stay legible
#
# Markers we surface (per lead msg#23363):
#   FR-K  — `[orochi] MCP reconnected at <iso-ts> after N attempt(s)`
#           (sidecar stderr; one line per recovery)
#   FR-L1 — Claude Code's deferred-tool cache flips back to ready
#           without `/mcp reconnect`. Not a log line — observed via
#           the agent pane being able to invoke an MCP tool. We
#           print a HINT row when the FR-K marker fires so the
#           operator knows to test a tool right then.
#   FR-M  — `[verdict=PASS|FAIL] in #<chan> msg#<id> by <user>`
#           (auditor-haiku stdout / its publish channel)
#   FR-N  — `tick=stale-pr found=<X> dispatched=<Y>`
#           (daemon-stale-pr stdout)
#
# This is a *drill* tool: zero state, no daemons of its own, no
# config file. Bash + tail + awk. Ctrl-C exits.

set -u

SIDECAR_LOG="${SIDECAR_LOG:-$HOME/.scitex/orochi/runtime/logs/sidecar.log}"
AUDITOR_LOG="${AUDITOR_LOG:-$HOME/.scitex/orochi/runtime/logs/daemon-auditor-haiku.log}"
STALE_PR_LOG="${STALE_PR_LOG:-$HOME/.scitex/orochi/daemon-logs/stale-pr-daemon.log}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sidecar-log)
            SIDECAR_LOG="$2"
            shift 2
            ;;
        --auditor-log)
            AUDITOR_LOG="$2"
            shift 2
            ;;
        --stale-pr-log)
            STALE_PR_LOG="$2"
            shift 2
            ;;
        -h|--help)
            cat <<'USAGE'
observe-recovery.sh — drill operator's single-screen view.

Usage:
  observe-recovery.sh [--sidecar-log PATH] [--auditor-log PATH]
                      [--stale-pr-log PATH]

Tails the three recovery-relevant logs concurrently and highlights
the FR-K reconnect line, FR-M verdict lines, and FR-N tick lines.
Defaults assume the standard sac-managed agent log layout.

Markers surfaced (per lead msg#23363):
  FR-K  — sidecar reconnect line "[orochi] MCP reconnected at <ts>"
  FR-L1 — printed HINT row when FR-K fires; operator tests MCP tool
  FR-M  — auditor verdict lines "[verdict=PASS|FAIL] in #..."
  FR-N  — daemon-stale-pr tick lines "tick=stale-pr found=X ..."

Ctrl-C exits.
USAGE
            exit 0
            ;;
        *)
            echo "unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

# Color helpers — only emit ANSI if stdout is a TTY (so piping to a
# log file stays readable).
if [[ -t 1 ]]; then
    C_RED=$'\033[31m'
    C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'
    C_CYAN=$'\033[36m'
    C_GRAY=$'\033[90m'
    C_RESET=$'\033[0m'
else
    C_RED=""
    C_GREEN=""
    C_YELLOW=""
    C_CYAN=""
    C_GRAY=""
    C_RESET=""
fi

annotate_sidecar() {
    awk -v RED="$C_RED" -v GREEN="$C_GREEN" -v YELLOW="$C_YELLOW" \
        -v GRAY="$C_GRAY" -v RESET="$C_RESET" '
        /MCP reconnected at/ {
            print GREEN "[FR-K]" RESET " " $0
            print YELLOW "  HINT (FR-L1): the deferred-tool cache should now invalidate. Test an MCP tool from any agent pane WITHOUT /mcp reconnect." RESET
            next
        }
        /ALARM: hub unreachable/ {
            print RED "[ALARM]" RESET " " $0
            next
        }
        /ws (disconnected|connecting|connected|error)/ {
            print GRAY "[sidecar]" RESET " " $0
            next
        }
        { print GRAY "[sidecar]" RESET " " $0 }
    '
}

annotate_auditor() {
    awk -v RED="$C_RED" -v GREEN="$C_GREEN" -v CYAN="$C_CYAN" -v RESET="$C_RESET" '
        /verdict=FAIL/ {
            print RED "[FR-M FAIL]" RESET " " $0
            next
        }
        /verdict=PASS/ {
            print GREEN "[FR-M PASS]" RESET " " $0
            next
        }
        { print CYAN "[auditor]" RESET " " $0 }
    '
}

annotate_stale_pr() {
    awk -v GREEN="$C_GREEN" -v YELLOW="$C_YELLOW" -v CYAN="$C_CYAN" -v RESET="$C_RESET" '
        /tick=stale-pr/ {
            print GREEN "[FR-N tick]" RESET " " $0
            next
        }
        /dispatched DM/ {
            print YELLOW "[FR-N DM]" RESET " " $0
            next
        }
        { print CYAN "[stale-pr]" RESET " " $0 }
    '
}

# Multiplex three tail streams. Background each, trap Ctrl-C, wait.
trap 'kill 0' SIGINT SIGTERM

echo "${C_CYAN}observe-recovery: tailing${C_RESET}"
echo "  sidecar : $SIDECAR_LOG"
echo "  auditor : $AUDITOR_LOG"
echo "  stale-pr: $STALE_PR_LOG"
echo "${C_GRAY}(missing files are tolerated — tail will retry once they appear; -F)${C_RESET}"
echo

if [[ -e "$SIDECAR_LOG" || -d "$(dirname "$SIDECAR_LOG")" ]]; then
    tail -F "$SIDECAR_LOG" 2>/dev/null | annotate_sidecar &
fi
if [[ -e "$AUDITOR_LOG" || -d "$(dirname "$AUDITOR_LOG")" ]]; then
    tail -F "$AUDITOR_LOG" 2>/dev/null | annotate_auditor &
fi
if [[ -e "$STALE_PR_LOG" || -d "$(dirname "$STALE_PR_LOG")" ]]; then
    tail -F "$STALE_PR_LOG" 2>/dev/null | annotate_stale_pr &
fi

wait
