#!/usr/bin/env bash
# disk-reaper.sh — thin wrapper around ``scitex-orochi disk
# reaper-dry-run``.
#
# The canonical implementation lives in
# ``src/scitex_orochi/_cli/commands/disk_cmd.py``. Flag contract
# preserved: ``--dry-run``, ``--yes``, ``--only``, ``--include``,
# ``--list``. Exit codes match the Python command.

exec scitex-orochi disk reaper-dry-run "$@"
