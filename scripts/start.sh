#!/usr/bin/env bash
# Start the Orochi server
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
exec python3.11 -m scitex_orochi._server "$@"
