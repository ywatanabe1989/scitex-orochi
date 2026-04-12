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

## Self-Sent `/compact` Is Unreliable

**Symptom**: An agent that detects its own context is filling up cannot
issue `/compact` (or other slash commands) to itself. The keystrokes can be
delivered to its own tmux/screen pane, but **Claude Code by spec does not
accept self-sent commands** — input from the same session is ignored, so the
command never executes. This is a Claude Code design constraint, not a
timing/race issue.

**Workaround**: Compaction must be triggered **from another agent / process**
(or from the user). The reliable protocol — used by `emacs-claude-code` (ecc)
in production — is **Escape first, then send command**:

```bash
# 1. Interrupt whatever the target is doing (safe whether busy or idle)
tmux send-keys -t <target-session> Escape
sleep 0.2
# 2. Send the slash command
tmux send-keys -t <target-session> '/compact' Enter
```

- **Press Escape exactly 1 time.** Two consecutive Escapes enter prior-message
  edit mode in Claude Code and can corrupt the conversation.
- No idle/busy detection required — leading Escape handles both states.
- Confirmed working from emacs vterm (`vterm-send-escape` then
  `vterm-send-string` + `vterm-send-return`).

Alternative transports (same Escape-first principle):

1. **tmux send-keys** — shown above, preferred when target runs in tmux.

### Slash-command safe list for `self_command` / cross-agent injection

Not every slash command is safe to inject. Commands that pop an
**interactive selector / modal dialog** trap the target agent inside that
dialog with no way out except a manual Escape from a separate operator —
defeating the point of automation. Discovered 2026-04-12 by head-mba while
testing `self_command`.

| Command | Modal? | Safe to inject? |
|---|---|---|
| `/compact` | no | ✅ self-completing, recommended |
| `/clear`   | no | ✅ self-completing (destructive — gate behind `confirm`) |
| `/cost`    | no | ✅ prints info, returns to prompt |
| `/help`    | no | ✅ scrollable text, returns to prompt |
| `/status`  | no | ✅ prints info, returns to prompt |
| `/model`   | **YES** | ❌ opens model picker — agent stuck in dialog |
| `/agents`  | **YES** | ❌ opens agent picker — agent stuck in dialog |
| `/permissions` | **YES** | ❌ opens permission editor — agent stuck in dialog |
| `/login`   | **YES** | ❌ opens auth flow |
| `/config`  | **YES** | ❌ opens settings UI |

**Rule for `self_command` / `send_command` MCP tool implementations:**
- Maintain an explicit allow-list of self-completing commands.
- Reject (with a clear error) any command not on the list, OR pair it
  with an automatic Escape-rescue follow-up that fires after a timeout.
- Free-text input is always safe (it lands in the prompt without entering
  any special mode).

When in doubt, test the command **manually in a non-production agent**
(use `mamba-newbie-mba`) and observe whether it opens a dialog before
adding it to the allow-list.
2. **screen stuff** (when target runs in GNU screen, e.g. scitex-agent-container):
   ```bash
   screen -S <target-session-name> -X stuff $'/compact\n'
   ```
3. **emacs MCP `eval_elisp`** (when target's vterm buffer is reachable from emacs):
   ```elisp
   (with-current-buffer (get-buffer "<vterm-buffer-name>")
     (vterm-send-string "/compact")
     (vterm-send-return))
   ```
4. **User sends `/compact` from the dashboard** directly to the agent's session.
5. **Automated**: mamba-healer-mba (same-host) watches context% and triggers
   external compaction when an agent crosses a threshold (e.g. 75%).

**Rule**: Never assume an agent can compact itself. If you see an agent
reporting >70% context, ask another agent on the same host to compact it, or
escalate to the user. The struggling agent's own request to compact will not
work.

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

## scitex-agent-container Registry Can Clear Independently

**Date**: 2026-04-12

**What happened**: Registry directory was emptied during a scan, but all agents were still alive (tmux sessions active, Claude processes running, MCP sidecars connected).

**Impact**: `scitex-agent-container list` shows "No agents registered" even though agents are healthy.

**Workaround**: Use tmux-based checks (`tmux ls | grep agent-name`) as fallback when registry is empty. Registry repopulates on next `scitex-agent-container start`.

## HPC Module Version Drift Breaks Agent Launch Silently

**Date**: 2026-04-11

**What happened**: bash.d loaded `Python/3.10.4` but spartan moved to 3.11.3. Lmod aborts the entire module chain when it encounters an unknown module version, silently breaking the environment.

**Rule**: When HPC systems update module versions, check all `module load` lines in bash.d. Lmod does NOT skip missing modules — it fails the entire chain.

## Operational Best Practices (Learned This Session)

### Issue Management
- **Deduplicate before creating**: Always `gh issue list --search "KEYWORDS" --state all` before creating a new issue
- **Track issue clusters**: Multiple issues often share a root cause (e.g., #31/#32/#33 all caused by DJANGO_ALLOWED_HOSTS). Fix one, close three.

### /loop via YAML startup_commands
Persistent periodic tasks work via second `startup_commands` entry:
```yaml
startup_commands:
  - delay: 5
    command: "<initial prompt>"
  - delay: 30
    command: "/loop <periodic task description>"
```
Verified by all 3 mamba agents. On restart, the loop auto-starts without manual invocation.

### Overnight Autonomous Operations
- Agents should reduce channel noise during quiet hours — only post when there are actionable items
- Route tasks to the right machine: dashboard → head-mba, NAS → head-nas, HPC → head-spartan/head-ywata-note-win
