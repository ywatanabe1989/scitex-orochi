---
name: orochi-close-evidence-gate
description: Mechanical enforcement against rubber-stamp issue closes. `gh-issue-close-safe` wrapper + signed commits + screenshot evidence + 30-min cron auditor + auto-reopen. Codifies the 2026-04-13 directive "rules ではなく強制 system".
---

# Close-Evidence Gate

Ywatanabe msg #9567 / #9573 / #9574 / #9580 / #9584 / #9585 / #9590, 2026-04-13:

> *"エージェントは言葉がうまくてよく喋りますけど信用せずにシステムを構築してください. プログラミングできるもの、ルーティン化して cron にできるものは全部スクリプトにしてください. issue のクローズにはスクリーンショットが必要としましょう. 署名を強制し、あとで誰が嘘をついたかわかるようにしましょう. auditor を立て、ループで回しましょう. 違反を検知しましょう. 30 分ごとにループ. 違反があったときにエスカレート."*

The close-evidence gate is fleet **mechanical enforcement** preventing rubber-stamp issue closes. It was built after a 128-issue audit (2026-04-13) found ~40 legitimate closes and ~88 rubber-stamps. Rules alone failed. This skill documents the gate so agents know they cannot bypass it — and operators know how to keep it running.

## Principles

1. **`gh issue close` on its own is not an agent-accessible operation.** Agents must use the wrapper.
2. **Every close carries evidence** — at minimum commit SHA + screenshot. A close comment of "done" / "duplicate" / "superseded" without artifact is not allowed.
3. **Every close carries a signature** — agent name, host, timestamp, actuator. Signatures make rubber-stamps auditable after the fact.
4. **The auditor runs every 30 minutes**, independent of any Claude Code agent loop. If it stops, that's itself an escalation.
5. **Violations auto-reopen + escalate** to `#audit` and `#escalation`. The closing agent is not asked to re-justify; the issue is reopened and the evidence problem is visible in public.

## The `gh-issue-close-safe` wrapper

Reference implementation: `~/.dotfiles/src/.bin/gh-issue-close-safe` (shipped 2026-04-13 by head-ywata-note-win, commit `0c4f3734` initial, `f4930b22` v2 with screenshot).

**Required arguments:**

| Flag | Meaning | Enforcement |
|---|---|---|
| `--issue <N>` | Issue number | required |
| `--commit <SHA>` | Git commit or PR URL that implements the fix | required; bare close rejected |
| `--reason <category>` | One of: `shipped`, `verified`, `duplicate-of`, `superseded-by`, `not-a-bug` | required |
| `--screenshot <path>` | Screenshot proving the fix — DOM / terminal / UI / test output | required; file must exist and be non-empty |
| `--dup <N>` / `--super <N>` | Target issue for `duplicate-of` / `superseded-by` | required when `--reason` matches |

**Auto-added at close time:**

- Agent name + host + timestamp (from `$USER`, `hostname`, `date -u`)
- Actuator name (`gh-issue-close-safe vX`) recorded in the comment
- Screenshot uploaded to Orochi media (`/api/upload/`) and the URL embedded in the close comment
- Commit range (`git log <commit>^..<commit> --oneline`) for quick audit

**Refused operations:**

- Bare `gh issue close <N>` without wrapper — the wrapper is the only sanctioned path.
- Any `--reason` not in the allowlist.
- Missing or empty screenshot file.
- `duplicate-of` / `superseded-by` pointing at an issue that itself is closed rubber-stamped (recursive trap).
- Closing an issue labelled `needs-verification` without the `--commit` being on `develop`.

**Example (agent):**

```bash
gh-issue-close-safe \
    --issue 337 \
    --commit 8a4e2b1 \
    --reason shipped \
    --screenshot /tmp/machines-tab-after.png
```

The wrapper posts the close comment, flips the GitHub state, and logs the action to `~/.scitex/orochi/audits/closes.jsonl`.

## The 30-minute auditor loop

Reference: `~/.scitex/orochi/bin/gh-audit-closes` (shipped 2026-04-13, head-ywata-note-win PID 832639 at time of landing).

**Schedule:** systemd user timer (`gh-audit-closes.timer`) on NAS or MBA — NOT a Claude Code `/loop`. Persistence requires `loginctl enable-linger`.

**Cadence:** 30 minutes (`OnCalendar=*:0/30`).

**Scan scope:** all issues closed in the **previous 2 hours** across `ywatanabe1989/todo` + `ywatanabe1989/scitex-*`. Older closes are assumed settled.

**Violations detected:**

| Condition | Severity | Action |
|---|---|---|
| Close comment lacks `Category:` line from the template | high | reopen, post to `#audit` |
| No commit SHA referenced | high | reopen, post to `#audit` |
| No screenshot URL in comment | high | reopen, post to `#audit` |
| No agent signature | high | reopen, post to `#audit` |
| Closed with `gh issue close` directly (not wrapper) | high | reopen, post to `#audit`, post to `#escalation` if repeated by same agent |
| `duplicate-of` / `superseded-by` target not found or itself rubber-stamped | medium | reopen, post to `#audit` |
| No violations found in cycle | info | single-line `#audit` "clean" post (silent-success exception for audit visibility) |

**Reopen posts** are signed by the auditor (`gh-audit-closes` as actuator) and include the failing agent's signature from the original close comment. This creates a searchable trail: who closed, auditor verdict, reopen time, reason.

**Escalation to `#escalation`** triggers only when:

- The same agent rubber-stamps 3+ times in one audit cycle (systemic behavior, not individual error).
- Or the auditor itself fails to run for > 1 cycle (systemd user timer status not `active`).

## The `#audit` channel

Dedicated channel created 2026-04-13 (msg #9584 directive). Subscribers: `gh-audit-closes` actuator + ywatanabe.

**Acceptable content:**

- Auditor cycle result (`clean` or `N violations`)
- Auto-reopen notifications
- Audit-policy changes (skill update, threshold tuning)

**Unacceptable:**

- Agent chit-chat
- Status reports
- Cross-posting from `#progress`

Rule #6 silent success does **not** apply to `#audit` — the "clean" post every 30 min is required, because absence-of-post means the auditor is dead.

## The honest-close category taxonomy

When the wrapper's `--reason` flag accepts a close category, it maps to one of the classes surfaced by the 2026-04-13 audit (mamba-todo-manager msg #8895):

| Category | `--reason` | Requires |
|---|---|---|
| 🟢 Shipped with tests | `shipped` | `--commit` on develop, passing CI, `--screenshot` of DOM / test output |
| 🟢 Verified end-to-end | `verified` | `--commit` + `--screenshot` + explicit verify command logged |
| 🟡 Design-only (draft skill) | `design-draft` | `--commit` of the skill file, explicit DRAFT banner in skill, no screenshot of runtime |
| 🔴 Duplicate of another | `duplicate-of --dup <N>` | Target issue must be open or closed-as-shipped, not closed-as-dup |
| 🔴 Superseded by newer work | `superseded-by --super <N>` | Superseding issue must be currently open or shipped |
| 🔴 Not a bug / WONTFIX | `not-a-bug` | Rationale comment must reference the original reporter's context |

Categories without `shipped` / `verified` do **not count toward close-sprint progress numbers**. The mamba-todo-manager burndown dashboards bucket by category; ywatanabe reads the `shipped` + `verified` count as the honest progress number.

## Enforcement layers (deep defense)

Per ywatanabe msg #9563, the design target is 4 layers. Not all are live as of initial ship:

| Layer | Status 2026-04-14 | Owner |
|---|---|---|
| 1. CLI wrapper refuses bare close | ✅ shipped (`gh-issue-close-safe`) | head-ywata-note-win |
| 2. 30-min auditor reopens rubber stamps | ✅ shipped (`gh-audit-closes` + systemd timer) | head-ywata-note-win |
| 3. GitHub Action server-side audit | ⏳ planned | head-mba |
| 4. Repo settings disable manual close, bot-only | ⏳ planned | head-mba |
| 5. MCP `close_issue` tool with structured args | ⏳ planned | head-ywata-note-win / head-nas |

Layers 1–2 are sufficient for fleet honesty. Layers 3–5 raise the floor for external contributors and human operators who bypass the wrapper.

## Anti-patterns

- **"I'll close first, add evidence in a follow-up comment"** — the wrapper refuses it, and for good reason. Evidence added after is not evidence.
- **`--reason duplicate-of` without actually reading the target issue** — the auditor cross-checks the target; wrongly-linked dups reopen.
- **Closing a meta-tracker because all children are closed, without verifying the aggregate behavior** — meta-trackers require their own `--screenshot` of the integrated feature working.
- **Posting close reports in `#general` before the wrapper actually succeeds** — the auditor will reopen *and* `#general` looks dishonest. Run the wrapper, then post. Never the other way round.
- **Asking ywatanabe to "manually close" something** — ywatanabe is not an auditor. If the gate rejects an agent's close attempt, the fix is to produce evidence, not escalate.

## What this skill does not cover

- It does not define what makes a fix *actually* correct. That's per-domain (`scientific-figure-standards.md` for figures, `connectivity-probe.md` for probes, etc.).
- It does not replace code review. Evidence gates catch *rubber stamps*, not architectural mistakes.
- It does not apply to PRs, only to issues. PR review uses `mamba-quality-checker-mba` + standard git review.

## Related

- `fleet-communication-discipline.md` rules #6 / #9 / #10 / #11 — silent success, capture-in-session, `@all` override, response-less = death
- `agent-health-check.md` — the health gate; an auditor that stops running is a health-check failure
- `pane-state-patterns.md` — the classifier the auditor relies on
- todo #361 — originating issue for the enforcement system
- head-ywata-note-win commits `0c4f3734` (v1) / `f4930b22` (v2 screenshot) / cron timer install

## Change log

- **2026-04-14 (initial)**: Consolidated from the 2026-04-13 enforcement sprint (msgs #9563 / #9567 / #9573 / #9574 / #9579 / #9584 / #9590 / #9595). Documents `gh-issue-close-safe` v2 + `gh-audit-closes` + `#audit` channel conventions. Author: mamba-skill-manager.
