#!/usr/bin/env bash
# chrome-codesign-clone-watchdog.sh — thin wrapper around
# ``scitex-orochi chrome-watchdog check``.
#
# Canonical implementation:
# ``src/scitex_orochi/_cli/commands/chrome_watchdog_cmd.py``.
#
# Flag contract preserved: ``--dry-run`` (``--help`` via click).
# Env vars ``ADVISE_GIB`` / ``REAP_GIB`` continue to work; the CLI also
# exposes them as ``--advise-gib`` / ``--reap-gib`` flags.

exec scitex-orochi chrome-watchdog check "$@"
