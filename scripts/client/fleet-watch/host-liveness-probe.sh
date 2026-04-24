#!/usr/bin/env bash
# host-liveness-probe.sh — thin wrapper around the ``scitex-orochi
# host-liveness probe`` CLI subcommand.
#
# The canonical implementation is now
# ``src/scitex_orochi/_cli/commands/host_liveness_cmd.py``. This wrapper
# is preserved so existing install helpers, launchd/systemd units, and
# ``fleet_watch.sh`` callers keep working verbatim after the CLI
# noun-verb migration.
#
# Flag contract preserved:
#   --dry-run         dry-run (default)
#   --yes | -y        actually revive
#   --host NAME       one host only
#
# Env parity: ``SSH_TIMEOUT``, ``SSH_CONNECT_TIMEOUT``,
# ``MACHINES_YAML``, ``SCITEX_AGENT_LOCAL_HOSTS`` are honoured by the
# CLI.

exec scitex-orochi host-liveness probe "$@"
