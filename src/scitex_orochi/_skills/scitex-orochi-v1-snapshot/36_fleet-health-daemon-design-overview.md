---
name: orochi-fleet-health-daemon-design-overview
description: Overview of the fleet-health-daemon design — ground rules, TL;DR, origin, and 3-layer architecture. See fleet-health-daemon-design.md (orchestrator) for the full split.
---

# fleet-health-daemon — Design (todo#146)

> **STATUS: DRAFT** design doc for `ywatanabe1989/todo#146`. Posted to
> #agent for fleet review before PR. Not canonical until ywatanabe GO +
> merge into the `_skills/scitex-orochi/` tree.

## 0. Ground rules

- **The daemon name is `fleet-health-daemon`.** No mythological or
  medical symbols. Same name in commit messages, file paths, class
  names, systemd unit names, log paths, and breadcrumb directories.
- **Phase 1 is Claude Code quota-state scraping.** Not docker stats,
  not cpu.pressure, not pane-state classification. Those are
  Phase 2 and later. ywatanabe msg#11775: "クロードコードアカウンから
  クォータ情報を取るのが最初".
- **Healers are redundancy, not the top-level framing.** One
  `mamba-healer-<host>` on every host, running in parallel, cross-
  probing each other via `active-probe-protocol.md`. No single
  healer is load-bearing. ywatanabe msg#11775: "ヒーラーは冗長化".
- **The 2-layer daemon/worker split from `fleet-role-taxonomy.md`
  applies unchanged**, and is what enables the Phase-1-first
  rollout: the quota collector is pure programmatic I/O (daemon),
  the interpretation and recovery are LLM judgment (workers).
- **Recovery actions for pane-stuck / wedge / context-full cases
  are part of the same design**, not a separate "permission
  prompts" workstream. ywatanabe msg#11789 on todo#142:
  "システマティックな蘇生試みと、エージェントの定期蘇生試みと
  合わせる必要がある". They land in Phase 4 as a recovery playbook.

## 1. TL;DR

The fleet-health-daemon is **not** a single Claude-backed agent.
It is a **2-layer stack** that follows the ratified
`fleet-role-taxonomy.md`:

1. **`fleet-health-daemon`** (process layer) — `role=daemon`,
   `function=[metrics-collector, quota-watcher, prober]`. Pure
   bash/python, no Claude session, no quota consumption. Runs every
   30 s on every agent host via the host's native scheduler
   (launchd on MBA, systemd --user on NAS/WSL, `.bash_profile` +
   tmux `sleep` loop on Spartan since no sudo / no systemd --user /
   no cron). Collects a fixed health vector per tick, with **Claude
   Code quota state as the first-class signal**, writes host-local
   NDJSON, drops breadcrumb touch-files only on threshold
   transitions.
2. **`mamba-healer-<host>`** (agent layer) — `role=worker`,
   `function=[prober, healer]`. One per host, always-on LLM-backed.
   Reads the fleet-health-daemon NDJSON + breadcrumbs as primary
   input, cross-probes peer hosts via DM ping + random-nonce, owns
   all LLM-judgment recovery actions (SIGINT, `/compact`,
   `tmux send-keys`, systemd restart, MCP process dedup kill). The
   mesh of healers is the redundancy — if any one healer goes dark,
   its peers notice via the active probe and escalate.

The defining axis (scitex-orochi PR #134, msg#11428): "does the
loop require LLM judgment to make its next decision?". Programmatic
threshold sampling → daemon. LLM interpretation + recovery choice →
worker. Phase 1 is entirely on the daemon side; Phase 3–4 re-wire
the existing workers to the new daemon output.

## 2. Origin

- 2026-04-09 `todo#146` filed ("dedicated healer agent" vision).
- 2026-04-14 scitex-orochi PR #134 landed the 2-layer role
  taxonomy; this design is the first application of the taxonomy
  to the healer concept.
- 2026-04-14 msg#11775 — ywatanabe reframed `todo#146`:
  1. drop the "caduceus" / mythological naming,
  2. healers are redundancy (per-host + mesh), not a single
     centralised agent,
  3. Claude Code quota-state is the first deliverable, not the
     broader multi-signal probe.
- 2026-04-14 msg#11788 — mamba-healer-nas feasibility report
  confirmed the JSONL scraping path: `~/.claude/projects/<ws>/*.jsonl`
  contains per-call `input_tokens` / `output_tokens` /
  `cache_read_input_tokens` / `cache_creation_input_tokens` /
  `service_tier` / `timestamp`, which gives cumulative 5h window
  usage and tier transitions without an Anthropic API call.
- 2026-04-14 msg#11789 — ywatanabe on todo#142: "systematic
  resurrection + periodic resurrection attempts need to be combined".
  Wedge/stuck recovery is integrated into this design's Phase 4, not
  spun off as a separate `todo#142` workstream.
- 2026-04-14 msg#11785 / #11791 — head-mba directives on name
  (`fleet-health-daemon`), on closing PR #145 and reopening as a
  fresh PR, on the one-file-multiple-phases structure, and on the
  specific Phase 4 recovery action playbook (permission prompt,
  extra-usage wedge, context-window-full, tmux stuck, MCP zombie).

## 3. Architecture — 3-layer model

Per ywatanabe msg#11801 + head-mba msg#11806, this design is a
**3-layer** decomposition on top of the 2-layer process/agent
taxonomy:

1. **Layer 1 — Automated handshake + quota sampling (daemon)**.
   Pure programmatic loop, 30 s cadence, emits NDJSON containing
   (a) Claude Code quota state (§4), (b) multi-signal host health
   (§5), (c) random-nonce handshake replies from peer hosts per
   `random-nonce-ping-protocol.md` (every other tick = 60 s
   effective). No LLM. No hub session. This is the
   "automated nonce handshake with quota numbers" ywatanabe
   asked for.
2. **Layer 2 — Ledger (daemon-written, worker-read)**. A
   structured "who answered / who didn't" record, derived from
   Layer 1's NDJSON. Schema: `{agent, last_probe_ts, last_reply_ts,
   missed_count, reply_latency_ms_p50, reply_latency_ms_p99,
   last_seen_signal}`. Written to
   `~/.scitex/orochi/probes/fleet-health-daemon/ledger.ndjson`
   host-locally; aggregated hub-side via `/api/fleet/health/`
   (Phase 2 deliverable). No LLM — it's pure arithmetic over
   Layer 1's raw records.
3. **Layer 3 — Escalation + recovery (worker, LLM-in-loop)**. The
   `mamba-healer-<host>` workers read the Layer 2 ledger, notice
   missed handshakes, LLM-judge whether a silent agent is
   legitimately busy or wedged, and run the recovery playbook
   (§7). One worker per host, cross-probing peers, fully
   redundant — no single load-bearing healer.

The Layer 1 nonce-handshake protocol itself is **not re-specced
here**; it is defined by the existing
`random-nonce-ping-protocol.md` skill (8-hex nonce format, 60 s
hard SLA, publisher/verifier ring scope matrix). This design only
adds:

- **Cross-host mesh topology** — who probes whom (§6 Phase 3)
- **Ledger schema** (Layer 2, tied to schema v3 above)
- **Layer 3 dispatch rules** — when the worker escalates from a
  missed-handshake observation to a recovery action from §7

```
╔═══════════════════════════════════════════════════════════════╗
║  AGENT LAYER (LLM-backed, quota-consuming)                    ║
║                                                               ║
║    mamba-healer-mba     (existing)                            ║
║    mamba-healer-nas     (existing)                            ║
║    mamba-healer-spartan          (planned, redundancy mesh)   ║
║    mamba-healer-ywata-note-win   (planned, redundancy mesh)   ║
║                                                               ║
║    role=worker  function=[prober, healer]                     ║
║                                                               ║
║    Reads fleet-health-daemon NDJSON + breadcrumbs locally +   ║
║    from peer hosts via SSH / hub aggregation endpoint.        ║
║    Cross-probes peers via active-probe-protocol.md DM ping +  ║
║    random-nonce. Chooses and executes recovery actions from   ║
║    the Phase 4 playbook. Escalates to #escalation when        ║
║    automated recovery fails or recurs. Each healer is         ║
║    redundant with every other healer — no single one is      ║
║    load-bearing.                                              ║
╠═══════════════════════════════════════════════════════════════╣
║  PROCESS LAYER (no LLM, quota-zero)                           ║
║                                                               ║
║    fleet-health-daemon                                        ║
║    role=daemon                                                ║
║    function=[metrics-collector, quota-watcher, prober]        ║
║    host: one instance per host (MBA/NAS/Spartan/WSL)          ║
║    cadence: 30 s                                              ║
║    runtime: launchd (MBA) / systemd --user (NAS/WSL) /        ║
║             tmux+sleep loop (Spartan, no sudo)                ║
║                                                               ║
║    Samples Claude Code quota state (Phase 1, primary) plus    ║
║    the broader multi-signal health vector (Phase 2). Writes   ║
║    host-local NDJSON, maintains transition state in memory,   ║
║    drops breadcrumb touch-files on threshold transitions.     ║
║    Never holds a hub WebSocket session. Never calls an LLM.   ║
║    Never acts on its observations.                            ║
╚═══════════════════════════════════════════════════════════════╝
```

