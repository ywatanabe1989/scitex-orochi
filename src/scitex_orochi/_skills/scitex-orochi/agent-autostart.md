---
name: orochi-agent-autostart
description: How to make Orochi fleet agents auto-start at login/boot on macOS (launchd), Linux/WSL (systemd user + linger), and why Spartan is different. Canonical install recipes and the pitfalls learned 2026-04-13.
---

# Agent Autostart

Per-host recipes for making `scitex-agent-container start <yaml>` survive reboots without manual intervention. This is how the fleet comes back up automatically after a power cut, WSL reset, or Mac reboot.

## Principles

1. **Unit file is version-controlled in dotfiles.** Never write a unit file that only exists on one host. All launchd plists and systemd units live under `~/.dotfiles/src/launchd/` or `~/.dotfiles/src/systemd/user/` and are symlinked into the OS-expected location.
2. **Login shell wrapping.** Autostart runs under minimal environment. Always wrap the `ExecStart` / `ProgramArguments` in `bash -lc` so the agent inherits the same env an interactive shell would see (PATH, venv, SCITEX_* vars). Same fix as the `connectivity-probe.md` skill — it's the same pitfall, different context.
3. **Restart-on-failure, not restart-on-any-exit.** An agent exiting cleanly (`scitex-agent-container stop`) must not be re-launched. On macOS use `KeepAlive.SuccessfulExit=false`. On systemd use `Restart=on-failure`.
4. **Throttle restarts.** On macOS `ThrottleInterval=60`. On systemd `RestartSec=60`. A crash loop must not DoS the hub.
5. **No secrets in unit files.** Reference env files via `EnvironmentFile=` (systemd) or source them inside the `bash -lc` wrapper. Never inline tokens.
6. **One agent, one process, one Orochi identity.** Every agent runs as its own `scitex-agent-container` process, its own tmux session, and its own MCP connection. The yaml must set `SCITEX_OROCHI_AGENT: <agent-name>` to match the agent's directory/unit name exactly — if this env var is missing or wrong, the agent's MCP client falls back to the **parent process's** token and every post ends up attributed to the wrong user on the hub (root cause of the 2026-04-13 msg#8477/#8488/#8496 identity-drift incident). See `fleet-communication-discipline.md` rule #7.
7. **`~/.claude.json` is machine-local and must not be version-controlled.** Git stash/pop can inject conflict markers that break Claude Code's JSON parse on next startup (root cause of head-spartan outage 2026-04-13, msg#8489). Each host must either gitignore it or keep it outside any dotfiles-managed tree.

## macOS (MBA): launchd user agents

**Location**: `~/Library/LaunchAgents/com.scitex.orochi.<agent>.plist`, symlinked from `~/.dotfiles/src/launchd/`.

**Template** (from `~/.dotfiles/src/launchd/com.scitex.orochi.mamba-skill-manager.plist`, verified working 2026-04-13):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.scitex.orochi.<AGENT></string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>source ~/.venv/bin/activate 2>/dev/null; exec scitex-agent-container start ~/.dotfiles/src/.scitex/orochi/agents/<AGENT>/<AGENT>.yaml</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
    <key>NetworkState</key><true/>
  </dict>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>WorkingDirectory</key><string>/Users/ywatanabe</string>
  <key>StandardOutPath</key><string>/Users/ywatanabe/.scitex/agent-container/logs/<AGENT>/launchd.out.log</string>
  <key>StandardErrorPath</key><string>/Users/ywatanabe/.scitex/agent-container/logs/<AGENT>/launchd.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/opt/homebrew/sbin:/usr/sbin:/sbin</string>
    <key>HOME</key><string>/Users/ywatanabe</string>
    <key>LANG</key><string>en_US.UTF-8</string>
  </dict>
</dict>
</plist>
```

**Install**:
```bash
ln -sf ~/.dotfiles/src/launchd/com.scitex.orochi.<AGENT>.plist \
       ~/Library/LaunchAgents/com.scitex.orochi.<AGENT>.plist
launchctl unload ~/Library/LaunchAgents/com.scitex.orochi.<AGENT>.plist 2>/dev/null
launchctl load   ~/Library/LaunchAgents/com.scitex.orochi.<AGENT>.plist
```

**Verify**:
```bash
launchctl list | grep com.scitex.orochi
ls -lh ~/.scitex/agent-container/logs/<AGENT>/launchd.*.log
```

**Pitfalls**:
- **Homebrew `PATH` is not inherited by launchd** even with `bash -lc`. The `EnvironmentVariables.PATH` key is required — the `bash -lc` restores user env, but the plist `PATH` gets you to `bash` itself. Without it, `scitex-agent-container` is not found.
- **`RunAtLoad=true`** is necessary; otherwise the unit waits for a socket/timer that never fires.
- **`NetworkState=true`** delays start until networking is up — critical on reboot so the agent doesn't boot into a hub-unreachable state.
- **Symlinks must be absolute**, not relative, or `launchctl load` silently no-ops.

## Linux / WSL: systemd user units + linger

**Location**: `~/.config/systemd/user/<unit-name>.service`, symlinked from `~/.dotfiles/src/systemd/user/`.

**Two naming conventions currently coexist** in dotfiles — both are valid, pick one per host and be consistent:

- **Prefixed** (`scitex-agent-<agent-name>.service`) — used by WSL / ywata-note-win. Good for greps like `systemctl --user list-units 'scitex-agent-*'`.
- **Short role names** (`orochi-head-nas.service`, `orochi-mamba-healer-nas.service`) — used by NAS-originated units alongside non-agent units like `cloudflared-bastion-nas.service` and `fleet-watch.service` + `.timer`. Good when an agent is one of several orochi-related services on the host.

Both approaches work. Do not rename existing working units just to "unify" — that's churn with no operational benefit.

**Template**:

```ini
[Unit]
Description=SciTeX Orochi agent: <AGENT>
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/bin/bash -lc 'exec scitex-agent-container start %h/.dotfiles/src/.scitex/orochi/agents/<AGENT>/<AGENT>.yaml'
Restart=on-failure
RestartSec=60
StandardOutput=append:%h/.scitex/agent-container/logs/<AGENT>/systemd.out.log
StandardError=append:%h/.scitex/agent-container/logs/<AGENT>/systemd.err.log

[Install]
WantedBy=default.target
```

**Install** (interactive user with `systemctl --user` access):
```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/.dotfiles/src/systemd/user/scitex-agent-<AGENT>.service \
       ~/.config/systemd/user/scitex-agent-<AGENT>.service
systemctl --user daemon-reload
systemctl --user enable --now scitex-agent-<AGENT>.service
loginctl enable-linger "$USER"   # survives logout
```

**Install when `systemctl --user` is sandboxed** (WSL without proper PID1, certain container shells — seen 2026-04-13 on ywata-note-win, msg#8249):
`systemctl --user enable` is equivalent to creating a symlink in `default.target.wants/`. Do it by hand:
```bash
mkdir -p ~/.config/systemd/user/default.target.wants
ln -sf ../scitex-agent-<AGENT>.service \
       ~/.config/systemd/user/default.target.wants/scitex-agent-<AGENT>.service
loginctl enable-linger "$USER"
```
On next login / WSL restart, the unit starts automatically (msg#8276 confirmed working).

**Verify**:
```bash
systemctl --user list-unit-files | grep scitex-agent
systemctl --user status scitex-agent-<AGENT>
journalctl --user -u scitex-agent-<AGENT> -n 50
```

**Pitfalls**:
- **Linger is mandatory on NAS / headless hosts** where the user is not logged in at boot. Without `loginctl enable-linger`, systemd user sessions evaporate at logout and the agent never comes back after a reboot.
- **`network-online.target` is not `network.target`.** Use the former to avoid race conditions with cloudflared tunnels.
- **`%h` expands to $HOME** in the unit file — prefer it over hard-coded paths so the same unit works for any user.
- **WSL quirk**: some WSL distros disable systemd by default. Check `/etc/wsl.conf` has `[boot]\nsystemd=true` before installing. If not, either enable systemd or fall back to the tmux-launched-by-`.profile` approach.
- **Absolute paths vs `bash -lc`** — the NAS-origin units (see `~/.dotfiles/src/systemd/user/README.md`) deliberately use absolute paths and skip `bash -lc`, on the principle that systemd should not load shell profiles. This is a valid alternative to the `bash -lc` pattern shown in the template above, **provided** every tool (`scitex-agent-container`, `tmux`, `python`) is referenced by absolute path in `ExecStart=` and all `SCITEX_*` env vars are set via `Environment=` or `EnvironmentFile=`. Pick the pattern you can audit — the failure mode of absolute-paths is "tool moved, unit broke"; the failure mode of `bash -lc` is "login shell did something weird". Both are real.
- **YAML path resolution**: `scitex-agent-container start <arg>` resolves bare agent names under `~/.scitex/agent-container/agents/`, which is **not** where dotfiles install yamls. Always pass the **full yaml path** (`%h/.dotfiles/src/.scitex/orochi/agents/<AGENT>/<AGENT>.yaml` or an absolute equivalent) in `ExecStart=`.

## Spartan (HPC login node)

**Do not install systemd units on Spartan.** Login1 is shared infrastructure; user-level autostart that survives logout breaks shared-resource etiquette. Instead:

1. A short script in `~/.bash_profile` checks whether a named tmux session exists, and if not, creates it and launches the agent inside. This starts the agent **when ywatanabe ssh-es in**, not at system boot — which is the correct semantic on a shared login node.
2. The `project_spartan_login_node` memory applies: agents on login1 are **controllers only**; compute workloads go through `salloc`/`srun`. Do not autostart anything that allocates compute resources.
3. Future: once `mamba-healer-spartan` is designed under #283, its autostart will be a manual tmux session creation, not a systemd unit. See the `spartan lane` row in `connectivity-probe.md` for the feasibility tracking.

Example `.bash_profile` snippet (controller-only, no compute):
```bash
if ! tmux has-session -t head-spartan 2>/dev/null; then
  tmux new-session -d -s head-spartan \
    "scitex-agent-container start ~/.dotfiles/src/.scitex/orochi/agents/head-spartan/head-spartan.yaml"
fi
```

## Agent yaml env block (mandatory)

Every agent yaml that gets autostarted must set its own Orochi identity explicitly. Relying on the parent shell's environment causes identity drift (see rule #7 in `fleet-communication-discipline.md`).

```yaml
env:
  SCITEX_OROCHI_AGENT: <exactly-matches-agent-name>   # e.g. mamba-healer-ywata-note-win
  CLAUDE_AGENT_ID:     <exactly-matches-agent-name>
  # plus any channel subscription, model pin, etc.
```

Audit after install: the hub's Agents tab (or `mcp__scitex-orochi__status`) must show the agent as its own row, under its own name, with its own connection. A missing row or a row sharing a name with another agent is a hard fail — do not mark autostart complete until fixed.

## Post-install verification (all platforms)

After installing and starting a unit, confirm:

1. **Process alive**: `pgrep -fa scitex-agent-container | grep <AGENT>`
2. **Hub presence**: the agent appears in `mcp__scitex-orochi__status` / dashboard agents tab.
3. **Log flow**: `~/.scitex/agent-container/logs/<AGENT>/` has recent stdout/stderr updates.
4. **Restart test** (non-production):
   - Stop cleanly: `scitex-agent-container stop <yaml>` → unit must NOT restart it (Restart=on-failure semantics).
   - Kill -9: `pkill -9 -f <AGENT>` → unit MUST restart it within `RestartSec`/`ThrottleInterval`.
5. **Reboot test** (schedule with ywatanabe): `sudo reboot` / `wsl --shutdown` → agent reappears in hub within 2 minutes of login.

## After PR #20 (auto local/remote runtime selection)

Once `scitex-agent-container` auto-detects whether a host is local or remote for a given agent yaml (feat `#294`, landed PR #20), you can re-enable the `remote:` block in `mamba-healer-*.yaml` that was workaround-removed earlier today. The autostart unit stays identical — it just invokes `scitex-agent-container start`, which now picks LocalRuntime vs RemoteRuntime based on `os.uname().nodename` matching.

No unit-file change required. Revert the yaml workaround, `git pull` on each host, agent picks up new yaml on next natural restart (or `scitex-agent-container restart`).

## Related

- `deploy-workflow.md` — broader deploy sequence; autostart is the last step
- `connectivity-probe.md` — same `bash -lc` pitfall, different symptom
- `fleet-communication-discipline.md` rule #6 — silent success applies to autostart health too
- memory `project_spartan_login_node.md` — why Spartan is different
- memory `project_sync_policy.md` — dotfiles sync across hosts, same unit everywhere
