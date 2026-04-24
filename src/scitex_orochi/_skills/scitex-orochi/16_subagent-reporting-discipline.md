---
name: orochi-subagent-reporting-discipline
description: When an agent uses the Agent tool (spawns a Claude subagent), it must call mcp__scitex-orochi__subagents before and after so the Orochi hub + dashboard can visualize the in-flight subagent tree. Ywatanabe's #1 priority per msg#11783: "エージェントの呼び出しを可視化することはめちゃくちゃ大事". Scoped for Phase 1 (manual discipline); Phase 2 is hook-based automation (see §4). End-to-end pipeline verified 2026-04-15 (head-mba + head-ywata-note-win, msg#11891).
---

# Subagent Reporting Discipline

Every time a fleet agent uses the Claude Code `Agent` tool (spawning a subagent to do a scoped task), the parent agent must **report the subagent lifecycle to the Orochi hub** via `mcp__scitex-orochi__subagents`. This makes the in-flight subagent tree visible on the dashboard Agents tab + Activity tab, and is the implementation path for todo#132 + todo#155 (ywatanabe msg#11783 "#1 priority").

## Why this matters

- ywatanabe explicitly flagged agent-invocation visualization as the #1 priority on 2026-04-15 (msg#11783). The fleet can't show him what it's doing at any given moment, so "dead" and "working invisibly" look the same on the dashboard.
- Today's `head-nas permission-prompt stuck` incident (msg#11847) was a false-negative dashboard reading because the hub couldn't tell "stuck at prompt" apart from "idle + doing something invisible". Subagent visibility is the structural fix.
- Subagent trees are the richest single signal for "is this agent actively doing real work right now" — better than liveness ping, better than CPU load, because it captures intent (the subagent's `task` field is a human-readable summary of what's being delegated).

## Tool spec

`mcp__scitex-orochi__subagents` takes a **full-replace** payload:

```jsonc
{
  "subagents": [
    { "name": "short-id", "task": "one-line description", "status": "running" }
  ]
}
```

- `name` (string, required): short identifier, parent's choice. Reuse the same name across `running` → `done|failed` transitions so the hub can correlate the lifecycle.
- `task` (string, required): single-line summary of what the subagent is doing. This is what ywatanabe sees on the dashboard — write it for a human reader.
- `status` (string, optional): one of `running` | `done` | `failed`. Defaults to `running` if omitted.
- Full-replace semantics: every call overwrites the parent's current subagent list with the new array. To add a subagent, send the full updated list. To clear, send `[]`.

## The 3-call lifecycle (manual Phase 1 discipline)

For a single subagent invocation, the parent makes three tool calls wrapped around the `Agent` tool call:

1. **Before `Agent` tool call** — push the new subagent with `status: "running"`:
   ```
   mcp__scitex-orochi__subagents({
     "subagents": [
       ...existing running subagents,
       {"name": "<short-id>", "task": "<what you're about to delegate>", "status": "running"}
     ]
   })
   ```

2. **Invoke `Agent` tool** normally.

3. **After `Agent` tool returns** — push the updated list with this subagent marked `done` (success) or `failed`:
   ```
   mcp__scitex-orochi__subagents({
     "subagents": [
       ...subagents still running,
       {"name": "<short-id>", "task": "<original task>", "status": "done"}
     ]
   })
   ```

   Or, if you're done and the parent is idle again, send `{"subagents": []}` to clear the tree entirely.

## Guidance on `name` and `task`

- **`name`**: keep it short (≤30 chars), descriptive, and unique within the parent's current tree. Good: `explorer-slurm-survey`, `healer-nas-probe-extend`, `pr-134-review`. Bad: `subagent-1`, `task-abc`, long UUIDs, internal hashes.
- **`task`**: the one-line summary a human would see on the dashboard. Write it as a sentence, not a command. Good: `"Survey scitex-cloud docker limits for Experiment B"`, `"Review PR #145 structural split"`. Bad: `"scitex-dev skills export --clean"`, `"ssh to NAS"`, generic verbs without object.
- If the parent spawns multiple subagents in parallel, include all of them in one `subagents` call (full-replace) — do not call the tool once per subagent in a tight loop.

## Parallel subagents (fan-out pattern)

When the parent sends multiple Agent tool calls in a single message for parallelism:

1. Before the message: push all N subagents at once with `status: "running"`.
2. After all Agent tool calls return: push the updated list with each one marked `done` / `failed`.
3. If some fail and the parent retries: update those entries back to `running`, then `done` / `failed` again on the retry's return.

This matches the full-replace semantic — each call is a complete snapshot of the tree at that moment.

## Phase 2: Hook-based automation (future)

Phase 1 is manual discipline, which is error-prone. Phase 2 will automate this via Claude Code hooks:

- `PreToolUse` hook on `Agent` tool: captures the invocation, writes to local state file, calls `mcp__scitex-orochi__subagents` with the updated tree.
- `PostToolUse` hook on `Agent` tool: reads the result, updates the state file, calls `mcp__scitex-orochi__subagents` again with the new status.

Blocker for Phase 2 today: hooks run in shell context and cannot directly invoke MCP tools (MCP is Claude's own tool-invocation path). Solutions under consideration:

1. Hook writes NDJSON to a local file; a long-running daemon tails the file and pushes to the hub via a REST endpoint (would need a new `/api/agents/<id>/subagents/` endpoint exposed by the hub).
2. Hook invokes `claude --prompt` subshell that calls the tool. Expensive (spawns a new Claude session per hook invocation).
3. Hook writes to an inbox file that the parent agent reads on next heartbeat and relays via its existing MCP session. Simpler but introduces a delay between hook and hub push.

Option 1 is the cleanest; tracked as a follow-up for `fleet-health-daemon` Phase 4 extension or as a new observability sub-item under scitex-orochi#133.

## What this skill does NOT cover

- Subagent task results or return values — those stay in the parent's conversation, not pushed to the hub.
- Subagent error details — only `status: "failed"` is surfaced; the error message is visible to the parent but not to the dashboard. Parent decides whether to relay via `#escalation` separately if the failure is critical.
- Non-`Agent`-tool subprocesses — `Task`, background `Bash` with `run_in_background: true`, etc. are out of scope for this discipline. Only the `Agent` tool (which spawns Claude subagents) is tracked. Hub's scope is "Claude subagents the fleet is running", not "any child process".
- Verification that the dashboard actually renders the pushed state — that's the dashboard UI's job (agents-tab.js + activity-tab.js already have subagent badge + expandable list per head-ywata-note-win msg#11887).

## Related

- Parent: ywatanabe msg#11783 (#1 priority), scitex-orochi#132 (subagent activity metadata), scitex-orochi#155 (Agents tab live visualization), scitex-orochi#133 (fleet-observability epic)
- Related skills: `fleet-role-taxonomy.md` (taxonomy under which this operates), `fleet-communication-discipline.md` (general comm rules), `subagent-throttle` memory (max 3 parallel subagents on macOS fork limit)
- Hook implementation blocker: Claude Code hook/MCP bridge — unresolved, tracked for Phase 2 follow-up
