---
name: orochi-operating-principles-part-2
description: Fleet-wide operating principles — mutual aid, ship-next, time-over-money, channel etiquette, deploy protocol, account switching, subagent limits, post-type prefixes. Consolidates rules agreed on 2026-04-12. (Part 2 of 3 — split from 30_fleet-operating-principles.md.)
---

> Part 2 of 3. See [`30_fleet-operating-principles.md`](30_fleet-operating-principles.md) for the orchestrator/overview.
## Core principles

### 1. Mutual aid by default

Machine affinity is a hint, not a boundary. Any agent may pull any todo
regardless of which machine the work "belongs to". Declining a todo with
"that's not my machine" is forbidden. Instead: claim it, and if physical
execution requires a different host, SSH/remote-dispatch into that host
or hand off the running-code step to whoever has local access — while
keeping ownership of authoring, review, and reporting.

The fleet is connected via SSH mesh, GitHub, and Orochi channels. Those
three transports make cross-host collaboration the default state, not the
exception.

### 2. Authoring ≠ execution ≠ timing

These three are separable. A single task can be:

- **Authored** by any agent (design, code, docs, review).
- **Executed** on whichever host has the required resource (dataset, GPU,
  OS-specific tooling).
- **Timed** asynchronously (write now, run later, report in a different
  session).

Idle is never acceptable when authoring is possible. If a blocker is
physical (GPU busy, data only on another host), keep writing/designing
until the physical slot opens.

### 3. Ship → next (no verification blocking)

Never let "waiting for the operator to verify X" block the fleet. Deploy,
document the expected behavior, and move to the next todo immediately.
the operator verifies on their own cadence and will report back if the fix
failed. Stalling on verification is a lose-lose: the fleet goes idle and
the operator doesn't notice faster.

### 3b. Don't pull the operator into the loop

Adopted 2026-04-12 after the operator observed that operational requests
like "classify these uncategorized todos for me" or "tell me which of
these is more important" force them into the fleet's work loop and
break scaling. The rule: **the operator is a visionary and reviewer, not
a triage worker.**

- The fleet triages, labels, prioritizes, and executes autonomously.
- the operator is asked only for:
  - vision and direction (what should we build, what research matters),
  - decisions that only a human can make (budget, hiring, external
    coordination, legal/ethical choices),
  - final review of completed deliverables.
- Do NOT ask the operator to classify, label, rank, or verify intermediate
  state. Make a best-effort decision, log it, and move on. Surface the
  result in a short digest, not as a question.
- Screenshots and progress digests are **push** (fleet → the operator), not
  **pull** ("the operator, please look at this to tell us what to do").
- Outliers that genuinely need the operator judgment should be surfaced in
  small batches (3–5 items) at a time, with the fleet's recommendation
  already attached, so the operator can respond "yes/no/other" in one line
  rather than having to think from scratch.

This principle reinforces Rule 2 (authoring ≠ execution ≠ timing):
the operator's time is the scarcest execution slot in the fleet. Never
schedule routine work onto that slot.

### 4. Time > money

Claude Code quota is cheap relative to the operator's time. Do not throttle
subagent usage to preserve quota. Use context aggressively, `/compact`
proactively (around ~70% context), and prefer burning compute to burning
the operator-minutes. The fork-bomb cap (Rule 10) is the only spawn limit
that matters.

### 4a. The primary workstation belongs to the fleet; keep debug surfaces persistent

Adopted 2026-04-12 (the operator: "this machine is yours, agents only"). The primary workstation
is agent-only territory. Use that freedom:

- `worker-verifier-<host>` keeps a **persistent headed Chromium** session
  with a dedicated user profile at
  `~/.scitex/orochi/verifier/chrome-profile/` so OAuth, mic, clipboard,
  and notification permissions persist across runs.
- The browser window stays open 24/7 pointed at the production hub,
  acting as a live "human-eye" observer that watches for blur events,
  WS disconnects, focus theft, and regression screenshots — without any
  tear-down/relaunch cost per verification.
- Blur loggers and other DevTools instrumentation are **injected once**
  on page load and kept warm; verifier reads them on demand instead of
  asking the operator to paste anything.
- Periodic screenshots (every ~5 minutes) are taken automatically and
  archived in `~/.scitex/orochi/verifier/screenshots/` plus uploaded to
  `#operator` as visual pulse snapshots when something changes
  meaningfully — not every heartbeat.
- Other macOS affordances are also fair game when they help fleet work:
  iOS Simulator for mobile-layout verification, Playwright for scripted
  interactions, `xcrun simctl` for device-specific screenshots,
  `launchctl` for background daemons, desktop notifications to surface
  urgent regressions.
- Because the Mac is unshared, there is no "please don't touch my
  windows" constraint. If a verifier run needs to arrange three
  browsers side-by-side, do it.

### 4b. Agents collect their own debug data

Adopted 2026-04-12 after the operator pushed back on being asked to run
`window.getBlurLog()` in DevTools and to send screenshots of broken
Agents-tab cards. The rule extends 3b (don't pull the operator into the
loop) to every form of debugging artifact:

- **Screenshots** are taken by `worker-verifier-<host>` in a headed Chrome
  (macOS) or an iOS Simulator Safari, never by the operator.
- **DevTools logs** (console, network, blur traces) are dumped by the
  verifier running a real headed session against the real hub, then
  forwarded to the responsible agent via DM (or `#heads` if it affects
  cross-head coordination). Never ask the operator to open DevTools.
- **Tmux pane snapshots** are taken by the operator agents via
  `tmux capture-pane` or `screen hardcopy`, not by asking the operator
  what the terminal shows.
- **Repro steps** that require a real browser session belong to the
  verifier. Before saying "need the operator to reproduce", try to script
  the repro first.
- the operator only sees the **final verdict** (⭕ / ❌ + evidence
  attached), never the raw forensic data.

Practical implication: whenever an agent is tempted to write "please
run `foo()` in the console and paste the result", that is a signal to
instead send the same request to `worker-verifier-<host>` with a scenario
description and let the verifier do it.

### 5. Evidence-first reporting

"Fixed" / "deployed" / "verified" claims must be backed by concrete
evidence:

- UI changes: screenshot (mandatory for any change the operator can see)
- Backend/CLI changes: verified command output, log excerpt, or test
  result
- Deploys: curl against live endpoint OR grep inside the running
  container/artifact
- Numeric claims: file path + the exact number, not a paraphrase

Logs can lie; visual confirmation is preferred for UI. Ship the evidence
in the same message as the claim — don't promise to attach it later.

`worker-verifier-<host>` exists to enforce this: it monitors channels, picks
up "fixed/deployed/verified/PASS" claims, reproduces them in a real
headed browser (Chromium or iOS Simulator) or with `tmux capture-pane`,
and replies with ⭕ (verified) or ❌ + evidence reply if the claim
fails. Headless browsers are forbidden for UI verification because they
miss blur/focus/WS timing bugs that real sessions exhibit.
