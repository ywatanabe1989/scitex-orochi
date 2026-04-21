#!/usr/bin/env bash
# hungry-signal.sh — thin wrapper around the ``scitex-orochi hungry-signal
# check`` CLI subcommand.
#
# The canonical implementation lives in
# ``src/scitex_orochi/_cli/commands/hungry_signal_cmd.py`` (PR landing the
# CLI noun-verb migration, msg#16414 / ywatanabe msg#16412). This wrapper
# preserves:
#   * the original path so install helpers, launchd/systemd units, and
#     cron entries that reference ``scripts/client/hungry-signal.sh``
#     keep working verbatim;
#   * the original flag contract (``--dry-run`` / ``--yes`` / ``--host``);
#   * the original exit-code semantics (handled by the Python command).
#
# New callers should prefer the CLI form directly:
#   scitex-orochi hungry-signal check --yes
#
# Environment variables (``SCITEX_HUNGRY_DISABLED``, ``HUNGRY_THRESHOLD``,
# ``HUNGRY_STATE_DIR``, ``HUNGRY_LOG_DIR``, ``HUNGRY_CURL_TIMEOUT``,
# ``SCITEX_OROCHI_TOKEN``, ``SCITEX_OROCHI_HUB_URL``,
# ``SCITEX_OROCHI_HOSTNAME``, ``MACHINES_YAML``) are all honoured by the
# CLI; nothing else to set here.

exec scitex-orochi hungry-signal check "$@"
