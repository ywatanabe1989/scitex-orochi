#!/bin/bash
# -*- coding: utf-8 -*-
# walltime_signal hook for sac's SlurmRuntime.
#
# Fires one hour before SLURM walltime (via SIGUSR1 --signal=B:USR1@3600)
# BEFORE the auto-resubmit `sbatch "$0"` runs. Best-effort POST to the
# Orochi hub so the dashboard knows the agent is about to rotate through
# a new allocation. Never fails the wrapper: swallow all errors.

set -uo pipefail

# Bail quietly if the hub URL / token isn't configured.
: "${SCITEX_OROCHI_HOST:=}"
: "${SCITEX_OROCHI_PORT:=8559}"
: "${SCITEX_OROCHI_TOKEN:=}"

if [[ -z "$SCITEX_OROCHI_HOST" || -z "$SCITEX_OROCHI_TOKEN" ]]; then
    echo "[walltime-notify] hub URL/token unset; skipping hub POST"
    return 0 2>/dev/null || true
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "[walltime-notify] curl not found; skipping hub POST"
    return 0 2>/dev/null || true
fi

_payload=$(
    cat <<EOF
{"agent_id": "${SAC_AGENT_ID}", "job_id": "${SAC_JOB_ID}", "hours_left": 1, "phase": "walltime_signal"}
EOF
)

# Best-effort: 5s timeout, one retry. Log the response to stderr so it
# lands in the sbatch wrapper's log file for forensics.
curl -fsS --max-time 5 --retry 1 \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${SCITEX_OROCHI_TOKEN}" \
    -X POST \
    "https://${SCITEX_OROCHI_HOST}:${SCITEX_OROCHI_PORT}/api/fleet/walltime-warn/" \
    -d "$_payload" >&2 || {
    echo "[walltime-notify] POST failed — continuing with auto-resubmit anyway" >&2
}
