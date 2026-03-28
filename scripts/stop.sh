#!/usr/bin/env bash
# Stop the Orochi server gracefully
set -euo pipefail

PID=$(pgrep -f "python -m orochi.server" || true)
if [ -n "$PID" ]; then
    echo "Stopping Orochi (PID $PID)..."
    kill -TERM "$PID"
    echo "Done."
else
    echo "Orochi is not running."
fi
