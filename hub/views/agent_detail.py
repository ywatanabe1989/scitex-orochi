"""Per-agent detail endpoint (todo#420 MVP).

Returns a single-screen payload for the Agents tab's per-agent page:
metadata, CLAUDE.md, cached terminal pane text, channel subscriptions,
MCP servers, and the current task. This is the read-only backing for
the per-agent sub-tab in ``hub/static/hub/agents-tab.js``.

Scope explicitly excludes:

- Pane-state classification (todo#419) — UI infers from ``liveness``.
- Cross-host SSH capture of the live tmux pane — kept best-effort
  against the already-cached ``pane_tail_block`` field pushed by
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

from hub.registry import get_agents

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
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
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
          "machine": str,
          "model": str,
          "uptime_seconds": int | None,
          "registered_at": iso8601 | None,
          "last_action_ts": iso8601 | None,
          "last_heartbeat": iso8601 | None,
          "liveness": str,
          "claude_md": str,
          "mcp_json": str,
          "pane_text": str,
          "pane_text_source": "cached" | "unavailable",
          "channel_subs": [str, ...],
          "mcp_servers": [str | dict, ...],
          "current_task": str,
          "context_pct": float | None,
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

    # Prefer the richer pane_tail_block pushed by agent_meta.py --push;
    # fall back to pane_tail, then advertise unavailable. We deliberately
    # do NOT reach out to a cross-host tmux capture-pane over SSH here —
    # that expansion is tracked in todo#420 follow-up.
    raw_pane = agent.get("pane_tail_block") or agent.get("pane_tail") or ""
    pane_text = redact_secrets(raw_pane) if raw_pane else ""
    pane_text_source = "cached" if raw_pane else "unavailable"

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
        "model": agent.get("model", ""),
        "uptime_seconds": uptime_seconds,
        "registered_at": agent.get("registered_at"),
        "last_action_ts": agent.get("last_action"),
        "last_heartbeat": agent.get("last_heartbeat"),
        "liveness": agent.get("liveness") or agent.get("status") or "unknown",
        "claude_md": redact_secrets(agent.get("claude_md") or ""),
        # todo#460: serve the workspace .mcp.json for the Agents tab viewer.
        # agent_meta.py --push (dotfiles PR #71) already redacts SCITEX_OROCHI_TOKEN
        # and similar secrets before pushing, but we redact again defense-in-depth
        # so any future push path that forgets still stays safe.
        "mcp_json": redact_secrets(agent.get("mcp_json") or ""),
        "pane_text": pane_text,
        "pane_text_source": pane_text_source,
        "channel_subs": sorted({c for c in (agent.get("channels") or []) if c}),
        "mcp_servers": list(agent.get("mcp_servers") or []),
        "current_task": agent.get("current_task", ""),
        "context_pct": agent.get("context_pct"),
        "pid": int(agent.get("pid") or 0),
        "subagents": list(agent.get("subagents") or []),
        "subagent_count": int(agent.get("subagent_count") or 0),
        "health": agent.get("health") or {},
    }
    return JsonResponse(payload)
