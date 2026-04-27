#!/usr/bin/env bash
# Context-management actuator for the per-host healer mesh (todo#284 / #285).
# Two strategies:
#   strategy=compact  → external /compact injection via tmux send-keys
#   strategy=restart  → scitex-agent-container restart <agent>
#
# DRY-RUN by default. Pass --live to actually execute.
# Refuses to act on its own session (head-nas) unless --allow-self is passed,
# because compacting the orchestrator mid-run would break the loop.

set -u

DRY_RUN=1
ALLOW_SELF=0
HOST=""
AGENT=""
STRATEGY=""
SESSION=""
LOG_FILE="${COMPACT_ACTUATOR_LOG:-$HOME/.scitex/orochi/fleet-watch/compact_actuator.log}"
SELF_AGENT="head-nas"

usage() {
    cat >&2 <<EOF
Usage: $0 --host <h> --agent <name> --strategy compact|restart [--session <name>] [--live] [--allow-self]
  --host         remote ssh target (use 'localhost' for self)
  --agent        agent name (also default tmux session name)
  --strategy     compact | restart
  --session      tmux session name if different from agent
  --live         actually execute (default = dry-run, log only)
  --allow-self   permit operating on \$SELF_AGENT (orchestrator). DANGEROUS.
EOF
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --host)        HOST="$2"; shift 2 ;;
        --agent)       AGENT="$2"; shift 2 ;;
        --strategy)    STRATEGY="$2"; shift 2 ;;
        --session)     SESSION="$2"; shift 2 ;;
        --live)        DRY_RUN=0; shift ;;
        --allow-self)  ALLOW_SELF=1; shift ;;
        -h|--help)     usage ;;
        *)             echo "unknown arg: $1" >&2; usage ;;
    esac
done

[ -z "$HOST" ] && usage
[ -z "$AGENT" ] && usage
[ -z "$STRATEGY" ] && usage
[ -z "$SESSION" ] && SESSION="$AGENT"

mkdir -p "$(dirname "$LOG_FILE")"
log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG_FILE"
}

# ---- safety guards ----
if [ "$AGENT" = "$SELF_AGENT" ] && [ "$ALLOW_SELF" -ne 1 ]; then
    log "REFUSE self-action on $AGENT (use --allow-self to override)"
    exit 3
fi

case "$STRATEGY" in
    compact|restart) ;;
    *) log "REFUSE unknown strategy: $STRATEGY"; exit 4 ;;
esac

# ---- build the command ----
case "$STRATEGY" in
    compact)
        # Inject /compact into the agent's tmux pane.
        # Sequence: Escape (clear any partial input) → "/compact" literal → Enter.
        # Two send-keys calls: text first (without Enter), then "Enter" key name.
        REMOTE_CMD="tmux send-keys -t '$SESSION' Escape; tmux send-keys -t '$SESSION' '/compact'; tmux send-keys -t '$SESSION' Enter"
        ;;
    restart)
        REMOTE_CMD="scitex-agent-container restart '$AGENT'"
        ;;
esac

if [ "$HOST" = "localhost" ] || [ "$HOST" = "$(orochi_hostname -s 2>/dev/null)" ] || [ "$HOST" = "nas" ]; then
    EXEC_PREFIX=""
    EXEC_DESC="local"
else
    EXEC_PREFIX="ssh -o ConnectTimeout=5 -o BatchMode=yes $HOST"
    EXEC_DESC="ssh:$HOST"
fi

log "PLAN host=$HOST agent=$AGENT strategy=$STRATEGY session=$SESSION exec=$EXEC_DESC"
log "PLAN cmd: $REMOTE_CMD"

if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN — not executing. Pass --live to apply."
    exit 0
fi

log "LIVE — executing now"
if [ -z "$EXEC_PREFIX" ]; then
    bash -c "$REMOTE_CMD" 2>&1 | tee -a "$LOG_FILE"
    rc=${PIPESTATUS[0]}
else
    $EXEC_PREFIX "$REMOTE_CMD" 2>&1 | tee -a "$LOG_FILE"
    rc=${PIPESTATUS[0]}
fi

log "LIVE result rc=$rc"
exit "$rc"
