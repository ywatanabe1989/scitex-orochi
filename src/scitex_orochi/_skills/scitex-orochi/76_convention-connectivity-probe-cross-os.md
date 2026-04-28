---
name: orochi-convention-connectivity-probe-cross-os
description: Cross-OS semantics for connectivity probes — Darwin is not Linux; common mistakes checklist. (Split from 59_convention-connectivity-probe-extras.md.)
---

> Sibling: [`59_convention-connectivity-probe-adoption.md`](59_convention-connectivity-probe-adoption.md) for adoption checklist + per-host status + per-lane issue templates.
## Cross-OS semantics — Darwin is not Linux

The same metric name means different things on macOS and Linux. Probes that assume Linux semantics produce false positives on Darwin hosts (primary workstation). Observed 2026-04-13, msg#8603 — third probe false positive of the session after the tmux-socket and stale-LAN-IP ones.

### Memory

**Wrong** (assumes Linux `free -m` semantics):
```bash
# Darwin "Pages free" is always tiny (~100 MB) by design — macOS uses
# inactive + speculative pages as reclaimable cache. Reporting this as
# "free memory" triggers bogus CRITICAL alerts.
vm_stat | awk '/Pages free/ {print $3 * 4096}'
```

**Right** on Darwin — any one of:
```bash
memory_pressure | awk '/System-wide memory free percentage/ {print $NF}'
# or
sysctl -n vm.page_free_count vm.page_inactive_count vm.page_speculative_count | \
  awk '{sum += $1} END {print sum * 4096}'
# or
vm_stat | awk '/Pages (free|inactive|speculative)/ {sum += $NF} END {print sum * 4096}'
```

**Right** on Linux:
```bash
free -m | awk '/Mem:/ {print $7}'   # "available" column, not "free"
# or
awk '/MemAvailable/ {print $2 * 1024}' /proc/meminfo
```

### Load average

`/proc/loadavg` is Linux-only. On Darwin use `sysctl -n vm.loadavg` or `uptime | awk -F'load average:' '{print $2}'`.

### Process counts

`pgrep -cf <pattern>` works the same on both, but `pgrep -x` behaves differently — on Darwin it matches only the process name (truncated at 15 chars historically). Prefer `pgrep -cf` unconditionally for probes.

### Disk usage

`df -h /` columns differ between GNU coreutils and BSD df. Parse by field name (`df -h / | awk 'NR==2 {print $4}'` for available) rather than by fixed column index.

### Shell alias override guard

Even after branching on `uname -s`, a login shell can still sabotage a probe by aliasing a coreutil to something interactive. Observed 2026-04-13: a user-level `alias free='watch -n 1 free -m'` on one host would have turned the memory probe into an endless `watch` loop had the probe used `bash -lc 'free -m'` (the `bash -lc` wrapper pulls in `.bashrc` aliases). Defenses:

- **`command free -m`** — `command` bypasses aliases and functions, calling the PATH builtin directly.
- **`\free -m`** — a leading backslash also disables alias expansion for that one invocation.
- **Absolute path**: `/usr/bin/free -m` / `/bin/free -m`.
- **`env free -m`** — runs `free` via `env`, which ignores shell aliases.
- **Subprocess list form** (Python / TS): `subprocess.run(["free", "-m"], shell=False)` — no shell, no aliases. This is what `scitex-agent-container snapshot.py` already does, so snapshot.py is immune even without the guards above.

Apply the same guard to any coreutil a probe calls: `ls`, `cp`, `mv`, `rm`, `grep`, `date`, `df`, `du`, `ps`, `free`, `uptime`. The user's dotfiles are not your dotfiles, and you will lose this fight on someone else's host.

Counter-pattern that motivates this rule: four unrelated probe false positives in one session (2026-04-13) all traced to the probing code trusting login-shell state on the target:
1. `tmux ls` without `$TMUX_TMPDIR` — socket mismatch
2. `ssh <host-alias>` routed to a stale LAN IP — host alias
3. `vm_stat Pages free` treated as free memory — Darwin semantics
4. `free` aliased to `watch -n 1 free` on one user — alias override

Each one looked like a different bug; the common root is "probe assumed shell/OS state instead of verifying it".

### Rule: branch on `uname -s`, never assume

Every probe that reads OS-level metrics must branch on the target host's OS, not the probing host's:

```bash
probe_mem() {
  local host="$1"
  ssh "${SSH_OPTS[@]}" "$host" "bash -lc '
    case \"\$(uname -s)\" in
      Darwin) memory_pressure | awk \"/System-wide memory free percentage/ {print \\\$NF}\" ;;
      Linux)  awk \"/MemAvailable/ {print \\\$2 * 1024}\" /proc/meminfo ;;
      *)      echo unknown ;;
    esac
  '"
}
```

The canonical `probe_remote.sh` under head-<host>'s `fleet_watch.sh` owns the cross-OS branching. If you find yourself writing OS-specific parsing outside that script, stop — extend `probe_remote.sh` instead of forking a second implementation.

## Common mistakes checklist

Before shipping any probe code, verify:

- [ ] `bash -lc` around every remote command
- [ ] `ConnectTimeout` and `BatchMode=yes` set on every `ssh` call
- [ ] SSH failure and empty result are distinguished in the output schema
- [ ] Escalation requires a compound condition, not a single metric
- [ ] Probe results written to a file, not just printed — rule #6 forbids routine chat posts
- [ ] Cross-OS metric parsing: every OS-level read (memory, load, disk) branches on `uname -s` of the **target** host, not the probing host. No Linux-only shortcuts (`/proc/loadavg`, `free -m $7`, `vm_stat Pages free` treated as free memory).
- [ ] Alias override guard: every coreutil invocation uses `command <tool>` / `\<tool>` / absolute path / subprocess list form. Never trust that `free`, `ls`, `df`, `ps`, etc. on a remote host resolve to the OS binary — user dotfiles can alias them to anything.
- [ ] primary workstation-specific: `tmux ls` works because `TMUX_TMPDIR` is set in `.bashrc` — confirm with `ssh <host> 'bash -lc "env | grep TMUX"'`. Memory probes must use `memory_pressure` / `vm.page_*_count`, never raw `Pages free` (that's always ~100 MB by design; treating it as a critical threshold false-alarms every tick).
- [ ] Spartan-specific: login1 has `squeue`/`sinfo`; compute nodes have a different view. Never probe compute nodes via ssh for fleet state.

