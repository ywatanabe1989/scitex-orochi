---
name: orochi-connectivity-probe
description: Canonical way to probe remote host liveness, tmux sessions, and process counts over SSH without the non-interactive-shell pitfalls that bite every naive implementation.
---

# Connectivity Probe

Every fleet healer, quality checker, and fleet_watch-style agent eventually needs to ask another host "are you alive, and how many claude/tmux/bun processes are running?" This skill codifies the one correct way to do it after repeated false positives (primary workstation reporting zero tmux sessions from secondary workstation on 2026-04-13, msg#8283 / #8319).

## The non-interactive shell pitfall

Naive:
```bash
ssh <host> 'tmux ls'          # often reports "no sessions"
ssh <host> 'pgrep -f claude'  # often reports 0
```

Why it fails: `ssh host 'cmd'` runs a **non-interactive, non-login** shell. That shell has not sourced `~/.bashrc` / `~/.profile` / `~/.bash_profile`, so:

- `$PATH` lacks user tools installed via Homebrew, nvm, pyenv, mise, uv, etc.
- `$TMUX_TMPDIR` is unset, so `tmux ls` looks in the wrong socket directory and finds nothing.
- `$DBUS_SESSION_BUS_ADDRESS` is missing on Linux, breaking `systemctl --user` calls.
- On macOS, the launchctl user agent environment is not inherited, hiding sessions started at login.

The result is silent under-reporting: probes claim a host has zero sessions when in reality it has nine. That's an operational-false-positive that triggers unnecessary `#escalation` pages.

## The fix: `bash -lc`

Wrap every remote command in a **login shell**:

```bash
ssh -o ConnectTimeout=5 -o BatchMode=yes <host> "bash -lc 'tmux ls 2>/dev/null | wc -l'"
ssh -o ConnectTimeout=5 -o BatchMode=yes <host> "bash -lc 'pgrep -cf claude'"
```

`bash -l` forces the shell to read profile files, restoring `$PATH`, `$TMUX_TMPDIR`, and any user environment that the sampled commands rely on. The single-quote wrapping prevents the local shell from expanding variables that should be resolved on the remote host.

## Required SSH flags

Every probe must set:

| Flag | Why |
|---|---|
| `-o ConnectTimeout=5` | Probe must not block the scan loop if a host is unreachable. |
| `-o BatchMode=yes` | Never prompt for a password — probes run unattended. |
| `-o StrictHostKeyChecking=accept-new` | New fleet hosts join without manual key dance; still rejects *changed* keys. |
| `-o ServerAliveInterval=5 -o ServerAliveCountMax=1` | Kill half-dead TCP sessions quickly. |

Combine:

```bash
SSH_OPTS=(-o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
          -o ServerAliveInterval=5 -o ServerAliveCountMax=1)

probe_host() {
  local host="$1"
  ssh "${SSH_OPTS[@]}" "$host" "bash -lc '
    tmux ls 2>/dev/null | wc -l;
    pgrep -cf claude 2>/dev/null || echo 0;
    pgrep -cf \"bun\" 2>/dev/null || echo 0;
    awk \"{print \\\$1}\" /proc/loadavg 2>/dev/null || uptime | awk -F\"load average:\" \"{print \\\$2}\" | awk -F, \"{print \\\$1}\"
  '"
}
```

## Graceful failure

Probe must distinguish three outcomes:

1. **SSH failed** (host unreachable, auth denied, timeout) — mark host `ssh=down`, do **not** infer anything about tmux/procs. Emit `unknown`, not `0`.
2. **SSH succeeded but the command errored** (e.g. `tmux` not installed) — mark `tmux=n/a`, continue.
3. **SSH succeeded and the command returned data** — trust the numbers.

Counter-pattern: treating "SSH succeeded + tmux returned 0" as "host has no sessions" when the real cause was a missing env. Always require a secondary signal (claude procs > 0, load > 0) before concluding that a host is degraded. Escalation policy should require **both** `ssh=down` *and* `claude_procs=0` for a confirmed outage, never just one.

## Canonical reference implementation

head-<host> owns the canonical implementation at `fleet_watch.sh` + `probe_remote.sh` (see msg#8098, 2026-04-13), producing JSON snapshots under `~/.scitex/orochi/fleet-watch/`. Fields:

```json
{
  "host": "<host-a>",
  "ts": "2026-04-13T06:00:00Z",
  "ssh": "up",
  "tmux_count": 9,
  "tmux_names": ["head-<host-a>", "worker-healer-<host-a>", ...],
  "claude_procs": 12,
  "bun_procs": 18,
  "load1": 2.34,
  "mem_used_pct": 51.0,
  "fork_pressure_pct": 7
}
```

Healers and quality checkers should **read these snapshots** rather than re-running probes themselves (see `infra-resource-hub.md` + rule #6 of `fleet-communication-discipline.md`). Running your own probe is acceptable only when:

- You need a field the canonical snapshot doesn't have, or
- You are the canonical implementation (head-<host>).

## Continued in

- [`59_convention-connectivity-probe-extras.md`](59_convention-connectivity-probe-extras.md)
