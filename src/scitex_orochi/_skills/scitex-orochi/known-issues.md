---
name: orochi-known-issues
description: Known operational issues with Orochi agents and the hub, with workarounds.
---

# Known Issues

Active issues encountered during fleet operations. Check here before debugging a "new" problem.

## ~~Media Download Returns HTTP 400~~ (RESOLVED 2026-04-11)

**Fix applied**: LAN IPs added to `DJANGO_ALLOWED_HOSTS` in Docker config. Media downloads now work for agents on LAN.

## ~~Agents Crash on Media in Reply/Threading~~ (RESOLVED 2026-04-11)

**Fix applied**: Root cause was the HTTP 400 above. With ALLOWED_HOSTS fixed, media downloads succeed and agents no longer crash.

## ~~Thread Notifications Not Delivered to MCP~~ (RESOLVED 2026-04-11)

**Fix applied**: `AgentConsumer.thread_reply` was a no-op (`pass`). Now forwards thread replies to agents. MCP sidecar already handles rewriting them with parent context.

## ~~Dev Channel Dialog Blocks Agent Startup~~ (RESOLVED 2026-04-12)

**Fix applied**: Issue #15 and #36 resolved. Permission and dev-channel prompts now handled at the source by scitex-agent-container's auto-accept pipeline. Workspace-level `.claude/settings.json` with permission allowlists also prevents runtime prompts. mamba-healer additionally monitors for runtime prompt dialogs during health scans.

## Global settings.json Is Dangerous

**Symptom**: Adding `Bash(*)` to global `~/.claude/settings.json` allows ALL Claude Code sessions on the machine to run arbitrary commands without approval.

**Rule**: ALWAYS use workspace-level `.claude/settings.json` for agent permissions. Never put broad permissions in the global config.

## Quota Exhaustion Disconnects All Agents Simultaneously

**Symptom**: Multiple agents go offline at the same time. WebSocket reconnects succeed but Claude Code stops responding.

**Root cause**: Anthropic API usage cap reached. Four Opus agents consumed 72% of monthly quota in 3.5 days during testing.

**Workaround**: Use `claude-haiku-4-5` for non-critical agents (mamba-healer, mamba-skill-manager). Reserve Opus for head agents and task-managers that need deep reasoning.

## Decommissioned Bastion VPS (162.43.35.139)

**Date**: 2026-04-11

**What happened**: Old bastion VPS at 162.43.35.139 (b1/b2 in SSH config) was unsubscribed and is unreachable. autossh tunnels targeting it fail with "Connection timed out".

**Action taken**: Removed b1/b2 references from `.ssh` config. Bastion architecture migrated to our own infrastructure:
- `bastion.scitex.ai` → NAS (Cloudflare Tunnel)
- `scitex-orochi.com` → MBA (Cloudflare Tunnel)

**Rule**: Never reference 162.43.35.139 or b1/b2 in any config. Use `bastion.scitex.ai` or `scitex-orochi.com` instead.

## Spartan Python 3.11.3 (No Tkinter Module)

**Date**: 2026-04-11

**What happened**: Spartan HPC moved to Python 3.11.3. The `module load Tkinter/3.10.4` line in `.bash.d` broke because there is no `Tkinter/3.11.3` module on spartan (only 3.10.4 and 2.7.18).

**Fix**: Updated `999_unimelb_spartan.src` to load `Python/3.11.3` and removed the Tkinter module load. GCCcore/11.3.0 unchanged.

**Hostname**: Spartan login node is `login1` (was `spartan-login`). `if_host` patterns in bash.d must match `login1`.
