#!/usr/bin/env bash
# disk-pressure-probe.sh — thin wrapper around ``scitex-orochi disk
# pressure-probe``.
#
# Canonical implementation:
# ``src/scitex_orochi/_cli/commands/disk_cmd.py`` (``pressure_probe``).
# The Python command accepts the same thresholds via
# ``--advisory-gib`` / ``--warn-gib`` / ``--critical-gib`` flags OR
# the ``DISK_FREE_{ADVISORY,WARN,CRITICAL}_GIB`` env vars. NDJSON still
# appended to ``$HOST_TELEMETRY_OUT_DIR/disk-pressure-<host>.ndjson``.
#
# Exit codes preserved: 0 ok, 1 advisory, 2 warn, 3 critical.

exec scitex-orochi disk pressure-probe "$@"
