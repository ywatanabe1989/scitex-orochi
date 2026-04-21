# LaunchAgents

macOS LaunchAgent templates installed per-user to protect host disk /
run client-side maintenance without interfering with the container.

## `com.scitex.chrome-codesign-watchdog.plist`

scitex-orochi#286 item 2. Periodically reaps the Chrome
`code_sign_clone` cache leak that contributed to the 2026-04-21
full-disk outage.

Install:

```bash
./scripts/client/install-chrome-codesign-watchdog.sh
```

Uninstall:

```bash
./scripts/client/install-chrome-codesign-watchdog.sh --uninstall
```

Status / logs:

```bash
launchctl list | grep com.scitex.chrome-codesign-watchdog
tail -n 50 ~/Library/Logs/scitex/chrome-codesign-watchdog.log
```

Thresholds (tune per host by editing the `EnvironmentVariables` block
in the installed plist and re-running the install helper):

- `ADVISE_GIB` (default 2) — log an advisory at this size
- `REAP_GIB` (default 5) — `rm -rf` the cache at this size

See `skills/infra-hub-docker-disk-full.md` for why this cache is
reaper-safe.
