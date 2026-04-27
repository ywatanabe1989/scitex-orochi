"""Per-agent detail endpoint (todo#420 MVP).

Returns a single-screen payload for the Agents tab's per-agent page:
metadata, CLAUDE.md, cached terminal pane text, channel subscriptions,
MCP servers, and the current task. This is the read-only backing for
the per-agent sub-tab in ``hub/static/hub/agents-tab.js``.

Scope explicitly excludes:

- Pane-state classification (todo#419) — UI infers from ``liveness``.
- Cross-host SSH capture of the live tmux pane — kept best-effort
  against the already-cached ``orochi_pane_tail_block`` field pushed by
  ``agent_meta.py --push``; the response advertises the source via
  ``pane_text_source`` so the frontend can show "cached" vs
  "unavailable" without inventing a new transport.
- Destructive quick-actions (Unblock / Restart / Kill). Only the
  read-only data surface ships here; the frontend adds a non-destructive
  DM quick-action that reuses the existing DM pipeline.

Privacy: ``pane_text`` is run through :func:`redact_secrets` before
serving so any token pasted into the pane by mistake does not escape
the hub. See :data:`_SECRET_PATTERNS` for the canonical list.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from hub.registry import get_agents, get_recent_singleton_event

# Canonical list of credential-ish strings to redact from terminal
# captures before serving them to the dashboard. These are matched as
# standalone tokens so ordinary prose is not mangled.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Anthropic API keys and OAuth access tokens.
    ("sk-ant", re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")),
    # GitHub personal access tokens / fine-grained tokens / app tokens.
    ("ghp", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    # JWTs (three base64url segments separated by dots). Used by OAuth
    # id_tokens, Django session JWTs, etc.
    (
        "jwt",
        re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    ),
    # OpenAI-style keys.
    ("sk-", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    # AWS access-key-id prefixes.
    ("aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # Generic "Bearer <token>" authorization headers in curl/log output.
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}")),
    # Anything that looks like a password-store grep result.
    ("password", re.compile(r"(?i)password[:=]\s*\S{4,}")),
)

# Matches a full line that contains credential-file paths. The whole line
# is dropped rather than masked so we don't leak an environment variable
# name followed by a masked value (the name itself is often sensitive).
_CREDENTIAL_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\.credentials\.json"),
    re.compile(r"(?i)\bpassword-store\b"),
    re.compile(r"(?i)\.env\.(local|secrets?)"),
)


def redact_secrets(text: str) -> str:
    """Replace credential-like substrings in ``text`` with ``[REDACTED]``.

    Best-effort: the goal is to stop copy-pasted tokens from reaching
    the dashboard, not to prove the absence of secrets. Tests pin the
    canonical patterns listed in :data:`_SECRET_PATTERNS`.
    """
    if not text:
        return ""
    cleaned: list[str] = []
    for line in text.splitlines():
        if any(p.search(line) for p in _CREDENTIAL_LINE_PATTERNS):
            cleaned.append("[REDACTED credential-referencing line]")
            continue
        for _label, pat in _SECRET_PATTERNS:
            line = pat.sub("[REDACTED]", line)
        cleaned.append(line)
    # Preserve a trailing newline when the source had one so the
    # frontend's scroll-to-bottom heuristic still works.
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(cleaned) + suffix


def _iso(ts: float | int | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _find_agent(name: str, candidates: Iterable[dict]) -> dict | None:
    for a in candidates:
        if a.get("name") == name:
            return a
    return None


def _resolve_workspace(request):
    """Return the authenticated workspace or a JsonResponse error.

    Accepts either an authenticated Django session (middleware already
    resolved ``request.workspace`` from the subdomain) or a workspace
    token passed via ``?token=wks_...``. This mirrors the auth shape
    of :func:`hub.views.api.api_agents` so agent_meta.py and the
    dashboard can both poll the endpoint.
    """
    workspace = getattr(request, "workspace", None)
    if workspace is not None and (request.user and request.user.is_authenticated):
        return workspace, None

    token = request.GET.get("token")
    if token:
        from hub.models import WorkspaceToken

        try:
            wt = WorkspaceToken.objects.select_related("workspace").get(token=token)
        except WorkspaceToken.DoesNotExist:
            return None, JsonResponse({"error": "invalid token"}, status=401)
        return wt.workspace, None

    if workspace is not None:
        # Session-less subdomain hit — refuse rather than leak.
        return None, JsonResponse({"error": "authentication required"}, status=401)
    return None, JsonResponse({"error": "authentication required"}, status=401)


@require_GET
def api_agent_detail(request, name: str):
    """GET /api/agents/<name>/detail — full single-screen payload.

    Response shape (stable; frontend pins these keys)::

        {
          "name": str,
          "role": str,
          "machine": str,                # YAML config label (join key)
          # #257 canonical heartbeat metadata — authoritative per-process
          # truth. Empty/None for legacy clients that haven't been
          # upgraded; UI falls back to `machine` until populated.
          "hostname": str,               # `hostname(1)` of the running process
          "orochi_hostname_canonical": str,     # FQDN via socket.getfqdn()
          "uname": str,                  # `uname -a` output
          "instance_id": str,            # UUID set once at agent boot
          "start_ts_unix": float | None, # Process start, epoch float
          "is_proxy": bool,              # True if rank > 0 in priority list
          "priority_rank": int | None,   # 0-based index in YAML host: list
          "priority_list": [str, ...],   # Full host: list from YAML
          "launch_method": str,          # sac | sac-ssh | sbatch | manual-* | unknown
          "heartbeat_seq": int | None,   # Monotonic per process
          "model": str,
          "uptime_seconds": int | None,
          "registered_at": iso8601 | None,
          "last_action_ts": iso8601 | None,
          "last_heartbeat": iso8601 | None,
          "liveness": str,
          "orochi_claude_md": str,
          "orochi_mcp_json": str,
          "orochi_pane_state": str,
          "orochi_stuck_prompt_text": str,
          "pane_text": str,
          "pane_text_source": "cached" | "unavailable",
          "channel_subs": [str, ...],
          "mcp_servers": [str | dict, ...],
          "orochi_current_task": str,
          "orochi_context_pct": float | None,
          "pid": int,
          "subagents": [ ... ],
          "health": { ... }
        }
    """
    workspace, err = _resolve_workspace(request)
    if err is not None:
        return err

    agents = get_agents(workspace_id=workspace.id)
    agent = _find_agent(name, agents)
    if agent is None:
        return JsonResponse({"error": "agent not found", "name": name}, status=404)

    # Prefer the richer orochi_pane_tail_block pushed by agent_meta.py --push;
    # fall back to orochi_pane_tail, then advertise unavailable. We deliberately
    # do NOT reach out to a cross-host tmux capture-pane over SSH here —
    # that expansion is tracked in todo#420 follow-up.
    raw_pane = agent.get("orochi_pane_tail_block") or agent.get("orochi_pane_tail") or ""
    pane_text = redact_secrets(raw_pane) if raw_pane else ""
    pane_text_source = "cached" if raw_pane else "unavailable"
    # todo#47 — ~500-line scrollback for the "Full pane" toggle. Same
    # redaction pipeline as pane_text; empty string if the agent's
    # agent_meta.py hasn't been updated yet (graceful degrade — the UI
    # falls back to the short pane_text).
    raw_pane_full = agent.get("orochi_pane_tail_full") or ""
    pane_text_full = redact_secrets(raw_pane_full) if raw_pane_full else ""

    # Compute uptime from registered_at ISO string when available.
    uptime_seconds: int | None = None
    reg_iso = agent.get("registered_at")
    if reg_iso:
        try:
            reg_dt = datetime.fromisoformat(reg_iso.replace("Z", "+00:00"))
            uptime_seconds = int(time.time() - reg_dt.timestamp())
        except (TypeError, ValueError):
            uptime_seconds = None

    payload = {
        "name": agent.get("name", name),
        "role": agent.get("role", ""),
        "machine": agent.get("machine", ""),
        # todo#55: canonical FQDN reported by the heartbeat, displayed
        # next to the short `machine` label in the detail header.
        "orochi_hostname_canonical": agent.get("orochi_hostname_canonical", ""),
        # ── #257 canonical heartbeat metadata ─────────────────────────
        # `hostname` is the authoritative `hostname(1)` of the running
        # process. The dashboard's `@host` label MUST be rendered from
        # this, not from `machine` (YAML config) — fabricated/cached
        # labels were the root of the ghost-mba bug (#256). Empty for
        # legacy clients that haven't been upgraded; UI falls back to
        # `machine` until the heartbeat carries it.
        "hostname": agent.get("hostname", ""),
        "uname": agent.get("uname", ""),
        "instance_id": agent.get("instance_id", ""),
        "start_ts_unix": agent.get("start_ts_unix"),
        "is_proxy": bool(agent.get("is_proxy")),
        "priority_rank": agent.get("priority_rank"),
        "priority_list": list(agent.get("priority_list") or []),
        "launch_method": agent.get("launch_method", ""),
        "heartbeat_seq": agent.get("heartbeat_seq"),
        # ── /#257 ─────────────────────────────────────────────────────
        "model": agent.get("model", ""),
        "uptime_seconds": uptime_seconds,
        "registered_at": agent.get("registered_at"),
        "last_action_ts": agent.get("last_action"),
        "last_heartbeat": agent.get("last_heartbeat"),
        # todo#46 — hub→agent ping RTT. Dashboard drives the PN lamp
        # off `last_pong_ts` (live when fresh) and `last_rtt_ms` (color
        # by latency).
        "last_pong_ts": agent.get("last_pong_ts"),
        "last_rtt_ms": agent.get("last_rtt_ms"),
        # #259 — 4th indicator (Remote / nonce-echo round-trip).
        # ``last_nonce_echo_at`` is the field the agent-badge LED
        # renderer consumes (already wired in agent-badge.js); the
        # other two surface RTT + raw unix timestamp for the per-agent
        # detail page tooling.
        "last_nonce_echo_at": agent.get("last_nonce_echo_at"),
        "last_echo_rtt_ms": agent.get("last_echo_rtt_ms"),
        "last_echo_ok_ts": agent.get("last_echo_ok_ts"),
        "liveness": agent.get("liveness") or agent.get("status") or "unknown",
        "orochi_claude_md": redact_secrets(agent.get("orochi_claude_md") or ""),
        # todo#460: serve the workspace .mcp.json for the Agents tab viewer.
        # agent_meta.py --push (dotfiles PR #71) already redacts SCITEX_OROCHI_TOKEN
        # and similar secrets before pushing, but we redact again defense-in-depth
        # so any future push path that forgets still stays safe.
        "orochi_mcp_json": redact_secrets(agent.get("orochi_mcp_json") or ""),
        # todo#418: agent decision-transparency for the Agents tab.
        # `orochi_pane_state` is the classifier label agent_meta.py --push
        # computes (`running` / `compose_pending_unsent` /
        # `y_n_prompt` / `auth_error` / etc.); `orochi_stuck_prompt_text`
        # is the verbatim prompt the agent is blocked on (empty
        # when `orochi_pane_state == running`). Both are redacted defense-
        # in-depth.
        "orochi_pane_state": agent.get("orochi_pane_state") or "",
        "orochi_stuck_prompt_text": redact_secrets(agent.get("orochi_stuck_prompt_text") or ""),
        "pane_text": pane_text,
        # todo#47 — longer scrollback; empty string when the agent
        # hasn't pushed it yet.
        "pane_text_full": pane_text_full,
        "pane_text_source": pane_text_source,
        "channel_subs": sorted({c for c in (agent.get("channels") or []) if c}),
        "mcp_servers": list(agent.get("mcp_servers") or []),
        "orochi_current_task": agent.get("orochi_current_task", ""),
        "orochi_context_pct": agent.get("orochi_context_pct"),
        "pid": int(agent.get("pid") or 0),
        "subagents": list(agent.get("subagents") or []),
        "orochi_subagent_count": int(agent.get("orochi_subagent_count") or 0),
        # Quota surfaced from agent_meta.py --push heartbeat. The heartbeat
        # stores `quota_5h_pct` / `quota_5h_remaining`; the UI reads
        # `quota_5h_used_pct` / `quota_5h_reset_at`. Map both shapes so
        # legacy payloads and newer fields coexist. Kept here so the
        # Agents tab meta-grid and Activity header chips can display
        # "5h X%" / "7d Y%" without a second round-trip.
        "quota_5h_used_pct": agent.get("quota_5h_used_pct")
        if agent.get("quota_5h_used_pct") is not None
        else agent.get("quota_5h_pct"),
        "quota_7d_used_pct": agent.get("quota_7d_used_pct")
        if agent.get("quota_7d_used_pct") is not None
        else agent.get("quota_7d_pct"),
        "quota_5h_reset_at": agent.get("quota_5h_reset_at")
        or agent.get("quota_5h_remaining")
        or "",
        "quota_7d_reset_at": agent.get("quota_7d_reset_at")
        or agent.get("quota_7d_remaining")
        or "",
        "health": agent.get("health") or {},
        # scitex-agent-container hook-event ring-buffer (PreToolUse /
        # PostToolUse / UserPromptSubmit). Empty lists when the hook
        # wiring hasn't been configured for this agent yet.
        "recent_tools": agent.get("recent_tools") or [],
        "recent_prompts": agent.get("recent_prompts") or [],
        "agent_calls": agent.get("agent_calls") or [],
        "background_tasks": agent.get("background_tasks") or [],
        "tool_counts": agent.get("tool_counts") or {},
        # Functional-heartbeat shortcuts.
        "last_tool_at": agent.get("last_tool_at") or "",
        "last_tool_name": agent.get("last_tool_name") or "",
        "last_mcp_tool_at": agent.get("last_mcp_tool_at") or "",
        "last_mcp_tool_name": agent.get("last_mcp_tool_name") or "",
        # PaneAction summary (scitex-agent-container action_store).
        "last_action_at": agent.get("last_action_at") or "",
        "last_action_name": agent.get("last_action_name") or "",
        "last_action_outcome": agent.get("last_action_outcome") or "",
        "last_action_elapsed_s": agent.get("last_action_elapsed_s"),
        "action_counts": agent.get("action_counts") or {},
        "p95_elapsed_s_by_action": agent.get("p95_elapsed_s_by_action") or {},
        # scitex-orochi#255: most recent singleton-cardinality conflict
        # for this agent within ``SINGLETON_EVENT_WINDOW_S``. ``None``
        # when no conflict has been recorded recently. Each event has
        # ``ts``, ``winner_instance_id``, ``loser_instance_id``,
        # ``reason``. The Agents tab uses this to surface a "another
        # process tried to claim this name" warning chip.
        "last_duplicate_identity_event": get_recent_singleton_event(name),
    }
    return JsonResponse(payload)
