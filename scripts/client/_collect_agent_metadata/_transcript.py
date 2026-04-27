"""Claude Code JSONL transcript parsing — orochi_model, orochi_context_pct, current tool, recent actions."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

# Tools to skip in orochi_current_tool / orochi_recent_actions selection. These are
# how the agent talks to the chat hub, NOT what the agent is actually
# working on. Showing them as orochi_current_task makes every idle agent look
# frozen on "reply" forever, which is the exact UX failure ywatanabe
# flagged at msg#6546 / msg#6551.
SKIP_TOOLS = {
    "mcp__scitex-orochi__reply",
    "mcp__scitex-orochi__react",
    "mcp__scitex-orochi__status",
    "mcp__scitex-orochi__history",
    "mcp__scitex-orochi__context",
    "mcp__scitex-orochi__health",
    "mcp__scitex-orochi__upload_media",
    "mcp__scitex-orochi__download_media",
    "mcp__scitex-orochi__rsync_media",
    "mcp__scitex-orochi__rsync_status",
    "mcp__scitex-orochi__self_command",
    "mcp__scitex-orochi__orochi_subagents",
    "mcp__scitex-orochi__task",
    "TodoWrite",
}


def _preview_for(tool_name: str, tool_input: dict) -> str:
    """Return a short label for the tool + its first arg.

    e.g. "Bash: docker compose build" instead of just "Bash".
    """
    if not isinstance(tool_input, dict):
        return tool_name
    short = tool_name
    arg = ""
    if tool_name == "Bash":
        arg = tool_input.get("command") or tool_input.get("description") or ""
    elif tool_name in ("Read", "Edit", "Write", "NotebookEdit"):
        arg = tool_input.get("file_path") or ""
    elif tool_name == "Glob":
        arg = tool_input.get("pattern") or ""
    elif tool_name == "Grep":
        arg = tool_input.get("pattern") or ""
    elif tool_name == "WebFetch":
        arg = tool_input.get("url") or ""
    elif tool_name == "WebSearch":
        arg = tool_input.get("query") or ""
    elif tool_name == "Agent":
        arg = tool_input.get("description") or ""
    elif tool_name.startswith("mcp__"):
        short = tool_name.split("__", 2)[-1]
        arg = (
            tool_input.get("query")
            or tool_input.get("text")
            or tool_input.get("description")
            or ""
        )
    else:
        # Generic: try common arg keys
        arg = (
            tool_input.get("description")
            or tool_input.get("query")
            or tool_input.get("name")
            or ""
        )
    if arg:
        arg = " ".join(arg.split())[:80]
        return f"{short}: {arg}"
    return short


def find_jsonl_transcripts(workspace: str) -> list[Path]:
    """Locate the Claude Code JSONL transcripts for an agent's workspace.

    Returns transcripts sorted newest-first. Empty list if the orochi_project
    directory doesn't exist.
    """
    encoded = workspace.replace("/", "-").replace(".", "-")
    encoded = re.sub(r"-{3,}", "--", encoded)
    proj_dir = Path.home() / ".claude" / "projects" / encoded
    if not proj_dir.is_dir():
        return []
    return sorted(
        proj_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )


def parse_transcript(jsonls: list[Path]) -> dict:
    """Parse the newest JSONL for orochi_model, orochi_context_pct, orochi_current_tool, orochi_recent_actions.

    Returns dict with keys: orochi_model, last_activity, orochi_context_pct,
    orochi_current_tool, orochi_started_at, orochi_recent_actions.
    """
    out = {
        "orochi_model": "",
        "last_activity": "",
        "orochi_context_pct": 0.0,
        "orochi_current_tool": "",
        "orochi_started_at": "",
        "orochi_recent_actions": [],
    }
    if not jsonls:
        return out

    jsonl = jsonls[0]
    try:
        lines = jsonl.read_text().splitlines()
    except Exception:
        lines = []
    tail = lines[-50:]

    # orochi_started_at = mtime of earliest jsonl for this orochi_project (ISO UTC)
    try:
        earliest = min(jsonls, key=lambda p: p.stat().st_mtime)
        out["orochi_started_at"] = datetime.fromtimestamp(
            earliest.stat().st_mtime, tz=timezone.utc
        ).isoformat()
    except Exception:
        pass

    # Most recent assistant turn -> orochi_model + orochi_context_pct
    for line in reversed(tail):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "assistant" and "message" in obj:
            msg = obj["message"]
            if not out["orochi_model"]:
                out["orochi_model"] = msg.get("orochi_model", "")
            if not out["last_activity"]:
                out["last_activity"] = obj.get("timestamp", "")
            u = msg.get("usage", {})
            total = (
                u.get("input_tokens", 0)
                + u.get("cache_read_input_tokens", 0)
                + u.get("cache_creation_input_tokens", 0)
            )
            out["orochi_context_pct"] = round((total / 1_000_000) * 100, 1)
            break

    # Pick the most recent meaningful tool use, skipping SKIP_TOOLS.
    orochi_current_tool = ""
    for line in reversed(tail):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "assistant":
            content = obj.get("message", {}).get("content", [])
            for c in content:
                if c.get("type") != "tool_use":
                    continue
                name = c.get("name", "")
                if name in SKIP_TOOLS:
                    continue
                orochi_current_tool = _preview_for(name, c.get("input") or {})
                break
            if orochi_current_tool:
                break
    out["orochi_current_tool"] = orochi_current_tool

    # Recent 10 actions with timestamps. ywatanabe msg#6608 wants the
    # card to feel like a mini activity log per agent: a vertical list
    # of "16:05:02 Bash: docker compose build" etc. Skips SKIP_TOOLS
    # housekeeping calls and pulls the last ~200 lines so we don't miss
    # anything in a busy turn.
    orochi_recent_actions: list[dict] = []
    wide_tail = lines[-200:] if lines else []
    for line in reversed(wide_tail):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "assistant":
            continue
        ts = obj.get("timestamp", "")
        content = obj.get("message", {}).get("content", [])
        for c in content:
            if c.get("type") != "tool_use":
                continue
            tname = c.get("name", "")
            if tname in SKIP_TOOLS:
                continue
            orochi_recent_actions.append(
                {"ts": ts, "preview": _preview_for(tname, c.get("input") or {})}
            )
            if len(orochi_recent_actions) >= 10:
                break
        if len(orochi_recent_actions) >= 10:
            break
    # Newest first → reverse to oldest first so the UI can render
    # top-down chronologically.
    orochi_recent_actions.reverse()
    out["orochi_recent_actions"] = orochi_recent_actions
    return out
