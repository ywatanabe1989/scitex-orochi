"""Top-level collect()/main() orchestrator — assembles the per-agent payload."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ._classifier import (
    _classify_pane_state,
    _detect_contradiction,
    _extract_stuck_prompt,
    _log_contradiction_evidence,
)
from ._files import (
    collect_claude_md,
    collect_mcp_json,
    collect_mcp_servers,
    collect_skills_loaded,
)
from ._hooks import _collect_hook_events
from ._hostname import _resolve_canonical_hostname
from ._machine import find_session_pids, resolve_machine_label
from ._metrics import collect_machine_metrics, collect_slurm_status
from ._multiplexer import detect_multiplexer
from ._pane import capture_pane, filter_pane_tail, parse_subagent_count
from ._proc import _read_process_env
from ._statusline import parse_statusline
from ._transcript import find_jsonl_transcripts, parse_transcript


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
        pid, ppid, started_at, workdir, project, machine, skills_loaded,
        runtime, version, subagent_count.
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
    pane_tail, pane_tail_block, pane_tail_block_clean, pane_tail_full = (
        filter_pane_tail(pane)
    )
    subagents = parse_subagent_count(pane)

    # Statusline (claude-hud) — context_pct, quota_5h, quota_weekly, model, email.
    sl = parse_statusline(pane_tail_block)
    statusline_context_pct = sl["statusline_context_pct"]
    quota_5h_pct = sl["quota_5h_pct"]
    quota_5h_remaining = sl["quota_5h_remaining"]
    quota_weekly_pct = sl["quota_weekly_pct"]
    quota_weekly_remaining = sl["quota_weekly_remaining"]
    statusline_model = sl["statusline_model"]
    account_email = sl["account_email"]

    # Locate latest transcript JSONL
    home = str(Path.home())
    workspace = f"{home}/.dotfiles/src/.scitex/orochi/workspaces/{agent}"
    jsonls = find_jsonl_transcripts(workspace)
    tr = parse_transcript(jsonls)
    model = tr["model"]
    last_activity = tr["last_activity"]
    context_pct = tr["context_pct"]
    current_tool = tr["current_tool"]
    started_at = tr["started_at"]
    recent_actions = tr["recent_actions"]

    # Process info: first claude child pid under the multiplexer session.
    pid, ppid = find_session_pids(agent, multiplexer)

    # Skills loaded + MCP servers from workspace files.
    skills_loaded = collect_skills_loaded(workspace)
    mcp_servers = collect_mcp_servers(workspace)
    project = agent
    machine = resolve_machine_label()

    # CLAUDE.md head + full, .mcp.json full (todo#460 viewers).
    claude_md_head, claude_md_full = collect_claude_md(workspace)
    mcp_json_full = collect_mcp_json(workspace)

    # Classifier (computed ONCE per collect — the stagnation counter
    # inside _classify_pane_state is per-cycle, so calling it twice
    # would double-increment the "pane unchanged for N cycles" count
    # and mis-fire `stale` after 2 real cycles instead of 3). The
    # `agent` kwarg enables cross-cycle stagnation tracking; omit it
    # and the classifier degrades to its legacy stateless behavior.
    pane_state = _classify_pane_state(pane_tail_block_clean, pane, agent=agent)
    stuck_prompt_text = _extract_stuck_prompt(
        pane_tail_block_clean, pane, agent=agent
    )
    # Contradiction check + evidence log. `alive=True` here means
    # we successfully captured a pane from the multiplexer, which is
    # the client-side equivalent of the hub's 4th-LED == green
    # (heartbeat fresh). When the classifier also says `stale`, that's
    # the msg#15541 contradiction — log the tmux tail so future
    # pattern additions have ground-truth data, and surface a
    # `classifier_note` on the payload so the Agents tab can flag it.
    classifier_note = _detect_contradiction(pane_state, liveness="online")
    if classifier_note:
        _log_contradiction_evidence(
            agent=agent,
            pane_state=pane_state,
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
        "multiplexer": multiplexer,
        "subagents": subagents,
        "subagent_count": subagents,
        "context_pct": (
            statusline_context_pct
            if statusline_context_pct is not None
            else context_pct
        ),
        "current_tool": current_tool,
        "current_task": current_tool,
        "quota_5h_pct": quota_5h_pct,
        "quota_5h_remaining": quota_5h_remaining,
        "quota_weekly_pct": quota_weekly_pct,
        "quota_weekly_remaining": quota_weekly_remaining,
        "statusline_model": statusline_model,
        "account_email": account_email,
        # Live tail of the agent's tmux pane — what the user would see
        # if they attached right now. Bypasses the JSONL transcript so
        # mid-tool-call activity (e.g. a streaming Bash command) shows
        # up. msg#6575 / msg#6582 / msg#6587.
        "pane_tail": pane_tail,
        "pane_tail_block": pane_tail_block,
        # todo#47 — ~500 filtered lines of tmux scrollback for the
        # agent-detail "Full pane" toggle in the Agents tab. 32 KB
        # cap applied in filter_pane_tail.
        "pane_tail_full": pane_tail_full,
        # ywatanabe msg#10657/10677: same as pane_tail_block but with
        # `← scitex-orochi · ...` channel inbound + `⎿` continuation
        # lines stripped, so consumers (fleet_watch.sh stuck-cycle
        # counter, pane_state.py classifier) can compute "did the agent
        # actually do anything?" without being fooled by inbound chatter.
        "pane_tail_block_clean": pane_tail_block_clean,
        "recent_actions": recent_actions,
        "last_activity": last_activity,
        "model": resolved_model,
        "pid": pid,
        "ppid": ppid,
        "started_at": started_at,
        "workdir": workspace,
        "project": project,
        "machine": machine,
        # todo#55: canonical FQDN for display next to the short machine
        # label in the dashboard.
        "hostname_canonical": _resolve_canonical_hostname(),
        "skills_loaded": skills_loaded,
        "mcp_servers": mcp_servers,
        "claude_md_head": claude_md_head,
        # todo#460 full-content fields for the Agents tab viewer.
        "claude_md": claude_md_full,
        "mcp_json": mcp_json_full,
        # todo#418: agent decision-transparency — classifier label + verbatim
        # stuck-prompt text. Computed from pane_tail_block_clean.
        # 2026-04-21 (lead msg#15541): the classifier now also emits
        # `stale` when the pane tail has been byte-identical for
        # N consecutive push cycles with no busy-animation marker. The
        # `classifier_note` field surfaces the 3rd-LED-stale-vs-4th-LED-green
        # contradiction with evidence appended to a dedicated log so
        # future pattern additions have ground-truth data.
        "pane_state": pane_state,
        "stuck_prompt_text": stuck_prompt_text,
        "classifier_note": classifier_note,
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
        "slurm": collect_slurm_status(),
    }
