# systemd user units

Linux counterparts to the macOS LaunchAgent templates in
`../launchd/`. Installed per-user via `systemctl --user` so the unit
survives logout only if `loginctl enable-linger $USER` has been run
(standard for fleet hosts).

## `scitex-worker-progress.service`

scitex-orochi#272. Long-running Python daemon that subscribes to
`#progress`, `#heads`, `#ywatanabe` and emits a 60 s throttled digest
line to `#ywatanabe`. See `scripts/server/worker-progress.py` and
`scripts/server/worker_progress_pkg/` for the implementation.

Install (live mode):

```bash
./scripts/client/install-worker-progress.sh
```

Install in dry-run smoke-test mode (no posts, just logged):

```bash
./scripts/client/install-worker-progress.sh --dry-run
```

Uninstall:

```bash
./scripts/client/install-worker-progress.sh --uninstall
```

Status / logs:

```bash
systemctl --user status scitex-worker-progress.service
journalctl --user -u scitex-worker-progress.service -f
tail -n 200 ~/.local/state/scitex/worker-progress.log
```

Requires `SCITEX_OROCHI_TOKEN` in `~/.scitex/orochi/env` (canonical
path — same file written by
`scripts/client/install/bootstrap-host.sh`). The unit uses
`EnvironmentFile=-%h/.scitex/orochi/env` (leading `-` = "don't fail if
missing"), so the daemon exits with a clear error if the token is
absent, rather than crashing systemd's restart loop.
