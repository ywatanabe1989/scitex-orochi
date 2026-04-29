"""Top-level collect()/main() orchestrator — assembles the per-agent payload."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ._classifier import (
    _detect_contradiction,
    _extract_stuck_prompt,
    _log_contradiction_evidence,
)
from ._files import (
    collect_orochi_claude_md,
    collect_orochi_env_file,
    collect_orochi_mcp_json,
    collect_orochi_mcp_servers,
    collect_orochi_skills_loaded,
)
from ._hooks import _collect_hook_events
from ._hostname import _resolve_canonical_hostname
from ._machine import find_session_pids, resolve_machine_label
from ._metrics import collect_machine_metrics, collect_orochi_slurm_status
from ._multiplexer import detect_multiplexer
from ._pane import capture_pane, filter_orochi_pane_tail, parse_orochi_subagent_count
from ._proc import _read_process_env
from ._process_tree import count_subagents_via_ps
from ._statusline import parse_statusline
from ._transcript import find_jsonl_transcripts, parse_transcript

# Heartbeat wire-format schema version. Bumped per release whenever the
# shape of the heartbeat payload changes (new fields are NOT a bump —
# additive changes are backward-compatible by design). Consumers (the
# hub at `hub/views/api/_agents_register.py`) check this against
# `MIN_SUPPORTED_SCHEMA` and refuse heartbeats that are too old, so a
# mixed-version fleet during a migration is *visible* on the wire
# instead of silently lagging the dashboard.
#
# History:
#   1 — initial introduction (2026-04-28).
HEARTBEAT_SCHEMA_VERSION = 1


def _build_a2a_section(agent: str) -> dict:
    """Run Layer A (a2a observations) + Layer B (orochi_comm_state v1).

    Returns a flat dict the caller spreads into the heartbeat payload.
    Keeps `sac_a2a_active_task_count` / `sac_a2a_active_task_state` / `sac_a2a_last_task_event_at`
    as derived top-level fields for back-compat with existing consumers.
    """
    from ._sac_a2a_observations import collect_sac_a2a_observations
    from .states._orochi_comm_state_v1 import derive_orochi_comm_state

    obs = collect_sac_a2a_observations(agent)
    verdict = derive_orochi_comm_state(obs)
    return {
        "sac_a2a_observations": obs,
        "orochi_comm_state": verdict["label"],
        "orochi_comm_state_evidence": verdict["evidence"],
        "orochi_comm_state_version": verdict["version"],
        # Back-compat: existing top-level scalars derived from the
        # observations. Consumers that already read these keep working.
        "sac_a2a_active_task_count": obs.get("sac_a2a_active_task_count", 0),
        "sac_a2a_active_task_state": obs.get("most_recent_task_state", ""),
        "sac_a2a_last_task_event_at": obs.get("most_recent_event_at"),
    }


def main(agent: str) -> None:
    """CLI entry point — print rich JSON for one agent.

    Refactored 2026-04-13 to call collect() so the legacy CLI path and
    the --push heartbeat path share a single source of truth, including
    the SKIP_TOOLS filter and tool input preview that hide the noisy
    mcp__scitex-orochi__* housekeeping calls (todo#155 / msg#6546).
    """
    print(json.dumps(collect(agent)))


def collect(agent: str) -> dict:
    """Return the same dict that ``main`` would print, without printing.

    Extends the legacy payload with fields required by the Orochi
    Agents-tab dashboard (todo#213):
        pid, ppid, started_at, workdir, project, machine, orochi_skills_loaded,
        runtime, version, orochi_subagent_count.
    Any field that can't be determined is omitted or left empty so the
    receiver can degrade gracefully.
    """
    multiplexer = detect_multiplexer(agent)
    if not multiplexer:
        return {"agent": agent, "alive": False, "multiplexer": ""}

    # Pane content -- subagent count from status bar AND the last
    # non-empty visible line so the Agents tab can show what the agent
    # is *literally typing right now*. ywatanabe at msg#6575 said the
    # tab "ちかちかしすぎてわからん、その割に tmux で最後の行取ってない"
    # — he wants the live tail of the pane in each card, not just the
    # JSONL-derived tool name. -J joins wrapped lines so a long
    # command isn't reported as several short fragments.
    pane = capture_pane(agent, multiplexer)
    (
        orochi_pane_tail,
        orochi_pane_tail_block,
        orochi_pane_tail_block_clean,
        orochi_pane_tail_full,
    ) = filter_orochi_pane_tail(pane)
    # Subagent count: prefer the process-tree walk (authoritative —
    # actually counts running ``claude`` descendants of the agent's
    # tmux/screen session) and fall back to parsing the pane marker if
    # the process-tree backend can't determine a number (returns -1).
    ps_count = count_subagents_via_ps(agent)
    subagents = ps_count if ps_count >= 0 else parse_orochi_subagent_count(pane)

    # Statusline (claude-hud) — orochi_context_pct, quota_5h, quota_weekly, model, email.
    sl = parse_statusline(orochi_pane_tail_block)
    statusline_orochi_context_pct = sl["statusline_orochi_context_pct"]
    orochi_quota_5h_pct = sl["orochi_quota_5h_pct"]
    orochi_quota_5h_remaining = sl["orochi_quota_5h_remaining"]
    orochi_quota_weekly_pct = sl["orochi_quota_weekly_pct"]
    orochi_quota_weekly_remaining = sl["orochi_quota_weekly_remaining"]
    orochi_statusline_model = sl["orochi_statusline_model"]
    orochi_account_email = sl["orochi_account_email"]

    # Locate latest transcript JSONL
    home = str(Path.home())
    workspace = f"{home}/.dotfiles/src/.scitex/orochi/workspaces/{agent}"
    jsonls = find_jsonl_transcripts(workspace)
    tr = parse_transcript(jsonls)
    model = tr["model"]
    last_activity = tr["last_activity"]
    orochi_context_pct = tr["orochi_context_pct"]
    orochi_current_tool = tr["orochi_current_tool"]
    started_at = tr["started_at"]
    recent_actions = tr["recent_actions"]

    # Process info: first claude child pid under the multiplexer session.
    pid, ppid = find_session_pids(agent, multiplexer)

    # Skills loaded + MCP servers from workspace files.
    orochi_skills_loaded = collect_orochi_skills_loaded(workspace)
    orochi_mcp_servers = collect_orochi_mcp_servers(workspace)
    project = agent
    machine = resolve_machine_label()

    # CLAUDE.md head + full, .mcp.json full (todo#460 viewers).
    orochi_claude_md_head, orochi_claude_md_full = collect_orochi_claude_md(workspace)
    orochi_mcp_json_full = collect_orochi_mcp_json(workspace)
    orochi_env_file_full = collect_orochi_env_file(workspace)

    # Classifier (computed ONCE per collect — the stagnation counter
    # inside _classify_orochi_pane_state is per-cycle, so calling it twice
    # would double-increment the "pane unchanged for N cycles" count
    # and mis-fire `stale` after 2 real cycles instead of 3). The
    # `agent` kwarg enables cross-cycle stagnation tracking; omit it
    # and the classifier degrades to its legacy stateless behavior.
    # Live hostname(1) — the kernel's answer to "where is this process
    # running right now". This is the authoritative host-identity signal
    # the hub's badge renderer (hostedAgentName) prefers over ``machine``.
    # Collected here so ``_build_payload`` can forward it unconditionally,
    # never letting env vars or server-side inference speak for the
    # process (lead msg#15578 root fix).
    import socket as _socket

    try:
        live_hostname = (_socket.gethostname() or "").split(".")[0].strip()
    except Exception:
        live_hostname = ""

    # Layer A (collect raw observations) → Layer B (derive verdict).
    # See AGENT_STATES.md for the architecture; ``_classifier.py`` retains
    # the legacy entry points (_extract_stuck_prompt, _detect_contradiction)
    # used by other call sites.
    from ._orochi_pane_observations import collect_orochi_pane_observations
    from .states._orochi_pane_state_v3 import derive_orochi_pane_state

    orochi_pane_observations = collect_orochi_pane_observations(
        orochi_pane_tail_block_clean, pane, agent=agent
    )
    pane_verdict = derive_orochi_pane_state(orochi_pane_observations)
    orochi_pane_state = pane_verdict["label"]
    orochi_stuck_prompt_text = _extract_stuck_prompt(
        orochi_pane_tail_block_clean, pane, agent=agent
    )
    # Contradiction check + evidence log. `alive=True` here means
    # we successfully captured a pane from the multiplexer, which is
    # the client-side equivalent of the hub's 4th-LED == green
    # (heartbeat fresh). When the classifier also says `stale`, that's
    # the msg#15541 contradiction — log the tmux tail so future
    # pattern additions have ground-truth data, and surface a
    # `orochi_classifier_note` on the payload so the Agents tab can flag it.
    orochi_classifier_note = _detect_contradiction(orochi_pane_state, liveness="online")
    if orochi_classifier_note:
        _log_contradiction_evidence(
            agent=agent,
            orochi_pane_state=orochi_pane_state,
            liveness="online",
            tmux_tail=pane,
        )

    # If the most recent assistant turn carried no real model label
    # (empty or a <synthetic>-style placeholder from compacted
    # summaries), fall back to the env var the runtime set at spawn.
    # The env is fetched from the claude process's own /proc/<pid>/environ
    # (the push script's own environment does NOT carry per-agent model
    # — each agent has its own model in its own process env).
    resolved_model = (
        model
        if model and not model.startswith("<")
        # Linux-only: peek at /proc/<pid>/environ for the real
        # model env the runtime set at spawn.
        else (
            _read_process_env(
                pid, ("SCITEX_AGENT_CONTAINER_MODEL", "SCITEX_OROCHI_MODEL")
            )
            # Darwin fallback: /proc doesn't exist. Check the pusher's
            # own env — on mba the tmux launcher exports
            # SCITEX_OROCHI_MODEL before spawning both claude and the
            # heartbeat helper, so they share the same env. Without
            # this the heartbeat keeps pushing "<synthetic>" (incident:
            # head-mba detail card, ywatanabe msg 2026-04-18 20:09).
            or os.environ.get("SCITEX_AGENT_CONTAINER_MODEL", "").strip()
            or os.environ.get("SCITEX_OROCHI_MODEL", "").strip()
            or model
        )
    )

    return {
        "agent": agent,
        "alive": True,
        # Wire-format schema version (see HEARTBEAT_SCHEMA_VERSION
        # comment at top of file). The hub uses this to drop heartbeats
        # too old to render and to surface mixed-version fleets.
        "orochi_heartbeat_schema_version": HEARTBEAT_SCHEMA_VERSION,
        "multiplexer": multiplexer,
        "subagents": subagents,
        "orochi_subagent_count": subagents,
        "orochi_context_pct": (
            statusline_orochi_context_pct
            if statusline_orochi_context_pct is not None
            else orochi_context_pct
        ),
        "orochi_current_tool": orochi_current_tool,
        "orochi_current_task": orochi_current_tool,
        "orochi_quota_5h_pct": orochi_quota_5h_pct,
        "orochi_quota_5h_remaining": orochi_quota_5h_remaining,
        "orochi_quota_weekly_pct": orochi_quota_weekly_pct,
        "orochi_quota_weekly_remaining": orochi_quota_weekly_remaining,
        "orochi_statusline_model": orochi_statusline_model,
        "orochi_account_email": orochi_account_email,
        # Live tail of the agent's tmux pane — what the user would see
        # if they attached right now. Bypasses the JSONL transcript so
        # mid-tool-call activity (e.g. a streaming Bash command) shows
        # up. msg#6575 / msg#6582 / msg#6587.
        "orochi_pane_tail": orochi_pane_tail,
        "orochi_pane_tail_block": orochi_pane_tail_block,
        # todo#47 — ~500 filtered lines of tmux scrollback for the
        # agent-detail "Full pane" toggle in the Agents tab. 32 KB
        # cap applied in filter_orochi_pane_tail.
        "orochi_pane_tail_full": orochi_pane_tail_full,
        # ywatanabe msg#10657/10677: same as orochi_pane_tail_block but with
        # `← scitex-orochi · ...` channel inbound + `⎿` continuation
        # lines stripped, so consumers (fleet_watch.sh stuck-cycle
        # counter, orochi_pane_state.py classifier) can compute "did the agent
        # actually do anything?" without being fooled by inbound chatter.
        "orochi_pane_tail_block_clean": orochi_pane_tail_block_clean,
        "recent_actions": recent_actions,
        "last_activity": last_activity,
        "model": resolved_model,
        "pid": pid,
        "ppid": ppid,
        "started_at": started_at,
        "workdir": workspace,
        "project": project,
        "machine": machine,
        # Live hostname(1) — see the comment above live_hostname for why
        # we send this unconditionally. The hub stores this as ``hostname``
        # distinct from ``machine`` (YAML label) and
        # ``orochi_hostname_canonical`` (FQDN).
        "hostname": live_hostname,
        # todo#55: canonical FQDN for display next to the short machine
        # label in the dashboard.
        "orochi_hostname_canonical": _resolve_canonical_hostname(),
        "orochi_skills_loaded": orochi_skills_loaded,
        "orochi_mcp_servers": orochi_mcp_servers,
        "orochi_claude_md_head": orochi_claude_md_head,
        # todo#460 full-content fields for the Agents tab viewer.
        "orochi_claude_md": orochi_claude_md_full,
        "orochi_mcp_json": orochi_mcp_json_full,
        "orochi_env_file": orochi_env_file_full,
        # todo#418: agent decision-transparency — classifier label + verbatim
        # stuck-prompt text. Computed from orochi_pane_tail_block_clean.
        # 2026-04-21 (lead msg#15541): the classifier now also emits
        # `stale` when the pane tail has been byte-identical for
        # N consecutive push cycles with no busy-animation marker. The
        # `orochi_classifier_note` field surfaces the 3rd-LED-stale-vs-4th-LED-green
        # contradiction with evidence appended to a dedicated log so
        # future pattern additions have ground-truth data.
        # Pane state pipeline:
        #   `orochi_pane_observations`        — Layer A primitive facts (digest,
        #                                 marker hits, idle chevron, etc.)
        #   `orochi_pane_state`               — Layer B v3 label (back-compat)
        #   `orochi_pane_state_evidence`      — Layer B reasoning string
        #   `orochi_pane_state_version`       — schema version for the verdict
        # Consumers can read just `orochi_pane_state` (legacy), or the full
        # observation dict to render their own classifications.
        "orochi_pane_observations": orochi_pane_observations,
        "orochi_pane_state": orochi_pane_state,
        "orochi_pane_state_evidence": pane_verdict["evidence"],
        "orochi_pane_state_version": pane_verdict["version"],
        "orochi_stuck_prompt_text": orochi_stuck_prompt_text,
        "orochi_classifier_note": orochi_classifier_note,
        # A2A state pipeline (Layer A → Layer B):
        #   `sac_a2a_observations`    — Layer A primitive facts (full task
        #                           list, tasks_by_state histogram,
        #                           endpoint reachability, etc.)
        #   `orochi_comm_state`          — Layer B v1 verdict label
        #   `orochi_comm_state_evidence` — Layer B reasoning string
        #   `orochi_comm_state_version`  — schema version
        # Plus three back-compat top-level fields derived from the
        # observations so existing consumers don't need to change yet.
        **_build_a2a_section(agent),
        # scitex-orochi #187 / #59 — hook-event ring buffer summary
        # from scitex-agent-container. Unpacked as top-level keys so
        # push_all()'s whitelist can forward each one verbatim.
        **_collect_hook_events(agent),
        "runtime": "claude-code",
        "version": os.environ.get("SCITEX_OROCHI_AGENT_META_VERSION", "0.1"),
        # Machine resource snapshot (todo#329 — Machines tab populate).
        "metrics": collect_machine_metrics(),
        # SLURM compute snapshot (todo#59). None on non-HPC hosts so the
        # Machines tab can hide the SLURM card cleanly.
        "orochi_slurm": collect_orochi_slurm_status(),
    }
