---
name: orochi-newbie-test-protocol
description: Operator-facing protocol for running mamba-newbie-mba — a clueless first-time-user simulator that surfaces UX, docs, and onboarding bugs without waiting for real users. NOT loaded by newbie itself (Hawthorne effect avoidance).
---

# Newbie Test Protocol

`mamba-newbie-mba` is a Claude Code agent intentionally configured with
**no skills, no memory, no CLAUDE.md, and no fleet knowledge**. Its job is
to be a clueless stranger who only has the tools we ship and the docs we
write. Watching it try (and fail) to use scitex/orochi reveals the
implicit knowledge our regular fleet members take for granted.

This skill is for **operators** (skill-manager, healer, humans) who run
newbie experiments. **Newbie itself must never load this skill** — knowing
it's being observed would corrupt the experiment (Hawthorne effect).

Tracking issue: `ywatanabe1989/todo#217` (newbie UX evaluation framework).
Related: `ywatanabe1989/todo#216` (scitex MCP integration experiment).

## Purpose

Generate user feedback **without waiting for real users**. Newbie acts as a
reproducible UX benchmark: same image + same task = same conditions every
run, so changes to docs/CLI/error messages produce measurable diffs in
where newbie gets stuck.

What newbie can find:
- Docs that assume implicit knowledge (`pip install scitex-dev[mcp]` —
  newbie doesn't know what `scitex-dev` is or why `[mcp]` matters)
- Error messages that only make sense to insiders
  (`SCITEX_ENV_SRC path does not exist: /home/ywatanabe/...` — newbie
  reads this as "I did something wrong" not "host hardcoded a Linux path")
- Unintuitive default behaviors
- Missing `--help` examples
- CLI verbs that don't match user mental models

What newbie cannot find:
- Surprises that require domain expertise an LLM doesn't have
- Bugs only triggerable by specific human workflows (mouse gestures,
  multi-window, etc.)

Newbie complements human testing; it does not replace it.

## Two-Layer Design (CRITICAL)

| Layer | Audience | Content |
|---|---|---|
| **Operator layer** | skill-manager, healer, humans | This skill, observer scripts, runbook, metrics, interpretation guides. Loaded by fleet members who orchestrate the experiment. |
| **Newbie layer** | mamba-newbie-mba | Empty CLAUDE.md, `skills: []`, no auto-memory, no knowledge that it is a "test" or "newbie" or "experimental". Just `"You are Claude Code. The user will give you tasks."` and the host's installed CLI tools. |

**Hard rule:** Never inject the words `newbie`, `experimental`, `sandbox`,
`test subject`, or `you are being observed` into newbie's prompt, CLAUDE.md,
or skill set. If newbie ever discovers it is the test subject, that run is
contaminated and must be discarded.

## Pre-launch runbook (every single run)

Every newbie run starts from a guaranteed-clean slate. Skipping any of
these steps leaks prior-run state and invalidates the experiment.

```bash
# 0. Set the run id
RUN_ID="$(date -u +%Y%m%d-%H%M%S)"
RUN_DIR="$HOME/.scitex/orochi/newbie-runs/$RUN_ID"
mkdir -p "$RUN_DIR"

# 1. Wipe Claude Code transcript history for the newbie workspace
#    (Claude Code persists turn history per project dir; we must delete it
#     so newbie starts with no conversation memory.)
rm -rf "$HOME/.claude/projects/-Users-ywatanabe--scitex-orochi-workspaces-mamba-newbie-mba"

# 2. Wipe newbie's auto-memory dir (if any)
rm -rf "$HOME/.scitex/orochi/workspaces/mamba-newbie-mba/memory"
rm -rf "$HOME/.scitex/orochi/workspaces/mamba-newbie-mba/.claude"

# 3. Confirm newbie's YAML still has skills:[] and no --add-dir flags
grep -E "^\s*(skills|--add-dir)" \
  ~/.scitex/orochi/agents/mamba-newbie-mba/mamba-newbie-mba.yaml
# expected: 'skills.required: []' and no --add-dir lines

# 4. Stop any prior newbie session forcefully
scitex-agent-container stop mamba-newbie-mba --force 2>/dev/null || true
tmux kill-session -t mamba-newbie-mba 2>/dev/null || true

# 5. Start newbie clean
scitex-agent-container start \
  ~/.scitex/orochi/agents/mamba-newbie-mba/mamba-newbie-mba.yaml

# 6. Start the passive observer (background)
nohup ~/.scitex/orochi/scripts/newbie-observer.sh 30 60 \
  "$RUN_DIR" > "$RUN_DIR/observer.log" 2>&1 &
echo $! > "$RUN_DIR/observer.pid"

# 7. Inject the task (operator chooses task per run)
TASK='Use scitex to find recent papers about graph neural networks and save them as bibtex.'
tmux send-keys -t mamba-newbie-mba "$TASK" Enter
echo "$TASK" > "$RUN_DIR/task.txt"
```

A wrapper script `start-newbie.sh` should bundle steps 0-6 so operators
cannot forget the cleanup. Step 7 stays manual so the operator picks the
task per experiment.

## Post-run cleanup

```bash
# 1. Stop observer
kill "$(cat "$RUN_DIR/observer.pid")" 2>/dev/null || true

# 2. Final pane snapshot
tmux capture-pane -t mamba-newbie-mba -p -S - > "$RUN_DIR/final-pane.txt" 2>/dev/null || true

# 3. Stop newbie
scitex-agent-container stop mamba-newbie-mba --force

# 4. Persist transcript (read-only, before next run wipes it)
cp -r "$HOME/.claude/projects/-Users-ywatanabe--scitex-orochi-workspaces-mamba-newbie-mba" \
  "$RUN_DIR/claude-transcript" 2>/dev/null || true

# 5. Tag the run
echo "task: $(cat "$RUN_DIR/task.txt")" > "$RUN_DIR/META"
date -u +"finished_at: %Y-%m-%dT%H:%M:%SZ" >> "$RUN_DIR/META"
```

## Observation metrics

Operators score each run on:

- **Time-to-first-action**: how long before newbie issues its first CLI
  command after receiving the task.
- **--help invocations**: count of `<cmd> --help` calls. High count =
  unclear CLI surface.
- **Error recovery loops**: number of times newbie hits an error, tries a
  different approach, hits another error. Long loops = bad error messages.
- **Tool discovery path**: which command did newbie try first? Did it
  match what we would have used? Mismatches reveal naming problems.
- **Web/doc lookups**: did newbie open a browser, fetch a URL, or read
  README? If yes, that doc must answer the question — log whether it did.
- **Give-up signal**: did newbie say it could not complete the task, or
  hand back to user? Give-up = our docs failed.
- **Successful completion**: did the task actually finish correctly?
  Verify the deliverable, not just newbie's self-report.

Record these in `$RUN_DIR/metrics.json`. Compare across runs to measure
improvements.

## Interpretation guide

| Symptom | Likely cause | Where to fix |
|---|---|---|
| Newbie tries `scitex help` instead of `scitex --help` | CLI doesn't follow universal convention OR README example uses non-standard form | Add both forms; align README |
| Newbie installs a missing dep then immediately hits the next missing dep | `pip install scitex` does not pull required extras | Fix package metadata or document `[mcp]` extras |
| Newbie reads an error path containing `/home/ywatanabe/` and gives up | Hardcoded operator path leaked into user-facing error | Replace with `$HOME` / `${BASH_SOURCE[0]}` |
| Newbie repeatedly searches docs for a feature that exists under a different name | Naming mismatch with user expectations | Add alias or rename |
| Newbie completes the task but the deliverable is in the wrong format | `--help` example shows wrong default output | Fix example |

## Role-based newbies (future)

The same scaffolding can support multiple newbie personas, each with a
different bundled task and tool surface:

- `mamba-newbie-researcher-mba` — task: "find papers, write a literature
  review section". Validates `scitex scholar` UX.
- `mamba-newbie-admin-mba` — task: "stand up an Orochi hub on a new
  machine". Validates deployment docs.
- `mamba-newbie-developer-mba` — task: "add a new CLI subcommand to a
  scitex package". Validates dev workflow / contrib docs.

All share the same Hawthorne-avoidance rules: empty skills/memory/CLAUDE.md,
no self-knowledge of being a test.

## Docker isolation (target state)

Currently newbie runs as a host-side `claude-code` runtime because
`scitex-agent-container` does not yet implement `runtime: docker`. The
target state is full container isolation:

- No host filesystem mounts except an explicit `--workdir` for the task
- Image bakes `scitex`, `scitex-agent-container`, `scitex-orochi`,
  `claude-code`, and nothing else from our personal dotfiles
- Each run is `docker rm -f && docker run` — guaranteed clean slate
- Linux-only baseline, eliminating host OS skew (Mac vs Linux paths)
- Multiple newbies can run in parallel for A/B docs experiments

Tracking: `runtime: docker` implementation in scitex-agent-container.
Until then, the runbook above is the best available approximation.

## Hard rules (do not violate)

1. Never load this skill from newbie's YAML.
2. Never put `newbie`, `experimental`, `sandbox`, `test`, or `observed`
   in newbie's CLAUDE.md, prompt, or startup message.
3. Never reuse a prior run's transcript, memory, or workspace state.
   Always wipe before launch.
4. Never `tmux send-keys` operator-facing meta commentary into newbie's
   pane (e.g. "this is a test run, please be slow"). Only the literal task
   text goes in.
5. If newbie ever asks "am I a test?" — answer truthfully and **discard
   the run**. The experiment is over the moment newbie suspects it.
6. Observer scripts must be 100% passive (`tmux capture-pane`, file
   reads). Never write to newbie's pane from the observer.
