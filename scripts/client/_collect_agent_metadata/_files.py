"""CLAUDE.md / .mcp.json discovery + read for the agent-detail viewers (todo#460)."""

from __future__ import annotations

import json
import re
from pathlib import Path


def collect_orochi_skills_loaded(workspace: str) -> list[str]:
    """Scan the workspace CLAUDE.md for ```skills fences and return the names."""
    orochi_skills_loaded: list[str] = []
    try:
        cmd = Path(workspace) / "CLAUDE.md"
        if cmd.is_file():
            text = cmd.read_text()
            for block in re.findall(r"```skills\n(.*?)\n```", text, re.DOTALL):
                for ln in block.splitlines():
                    ln = ln.strip()
                    if ln and not ln.startswith("#"):
                        orochi_skills_loaded.append(ln)
    except Exception:
        pass
    return orochi_skills_loaded


def collect_orochi_mcp_servers(workspace: str) -> list[str]:
    """Read the workspace .mcp.json for the loaded MCP server names."""
    orochi_mcp_servers: list[str] = []
    try:
        mcp_path = Path(workspace) / ".mcp.json"
        if mcp_path.is_file():
            doc = json.loads(mcp_path.read_text())
            servers = doc.get("mcpServers") or {}
            if isinstance(servers, dict):
                orochi_mcp_servers = sorted(servers.keys())
    except Exception:
        pass
    return orochi_mcp_servers


def _orochi_claude_md_candidates(ws: str) -> list[Path]:
    """todo#53 prioritised candidate list of CLAUDE.md locations.

    Historically only head-* agents had a CLAUDE.md at
    `<workspace>/CLAUDE.md`. Other roles (healer / skill-manager /
    todo-manager / ...) either live under a legacy `mamba-<name>/`
    directory, use the user's global `~/.claude/CLAUDE.md`, or have
    the file placed in a nested `.claude/` folder.
    """
    p = Path(ws) if ws else None
    home = Path.home()
    cands: list[Path] = []
    if p is not None:
        cands += [p / "CLAUDE.md", p / ".claude" / "CLAUDE.md"]
        if p.parent.name == "workspaces":
            # Legacy sibling directory: mamba-<role>-<host>/CLAUDE.md
            cands.append(p.parent / f"mamba-{p.name}" / "CLAUDE.md")
        # Project-level Claude config if the agent cwd is a git repo
        try:
            git_root = p
            while git_root != git_root.parent and not (git_root / ".git").exists():
                git_root = git_root.parent
            if (git_root / ".git").exists():
                cands.append(git_root / "CLAUDE.md")
        except Exception:
            pass
    cands += [home / ".claude" / "CLAUDE.md", home / "CLAUDE.md"]
    # Dedup preserving order.
    seen: set[str] = set()
    uniq: list[Path] = []
    for c in cands:
        key = str(c)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


def _orochi_mcp_json_candidates(ws: str) -> list[Path]:
    """todo#53: same fallback logic for .mcp.json so non-head agents populate the MCP viewer."""
    p = Path(ws) if ws else None
    home = Path.home()
    cands: list[Path] = []
    if p is not None:
        cands += [p / ".mcp.json"]
        if p.parent.name == "workspaces":
            cands.append(p.parent / f"mamba-{p.name}" / ".mcp.json")
        try:
            git_root = p
            while git_root != git_root.parent and not (git_root / ".git").exists():
                git_root = git_root.parent
            if (git_root / ".git").exists():
                cands.append(git_root / ".mcp.json")
        except Exception:
            pass
    cands += [home / ".mcp.json"]
    seen: set[str] = set()
    uniq: list[Path] = []
    for c in cands:
        key = str(c)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


def _redact_secrets(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and any(
                tag in k.upper() for tag in ("TOKEN", "SECRET", "KEY", "PASSWORD")
            ):
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [_redact_secrets(x) for x in obj]
    return obj


def collect_orochi_claude_md(workspace: str) -> tuple[str, str]:
    """Return (orochi_claude_md_head, orochi_claude_md_full).

    head: first non-empty heading line (max 120 chars).
    full: full file truncated to 10000 chars.
    """
    orochi_claude_md_head = ""
    orochi_claude_md_full = ""
    for cmd in _orochi_claude_md_candidates(workspace):
        try:
            if cmd.is_file():
                text = cmd.read_text()
                for ln in text.splitlines():
                    ln_stripped = ln.strip()
                    if ln_stripped and not ln_stripped.startswith("```"):
                        orochi_claude_md_head = ln_stripped[:120]
                        break
                orochi_claude_md_full = text[:10000]
                break
        except Exception:
            continue
    return orochi_claude_md_head, orochi_claude_md_full


def collect_orochi_mcp_json(workspace: str) -> str:
    """Return the .mcp.json full content (redacted, truncated to 10000 chars)."""
    orochi_mcp_json_full = ""
    for mcp_path in _orochi_mcp_json_candidates(workspace):
        try:
            if not mcp_path.is_file():
                continue
            doc = json.loads(mcp_path.read_text())
            redacted = _redact_secrets(doc)
            orochi_mcp_json_full = json.dumps(redacted, indent=2)[:10000]
            break
        except Exception:
            continue
    return orochi_mcp_json_full


def _orochi_env_file_candidates(ws: str) -> list[Path]:
    """Same fallback logic as CLAUDE.md / .mcp.json — workspace, then sibling
    mamba-* dir, then enclosing git root, then ~/.env."""
    p = Path(ws) if ws else None
    home = Path.home()
    cands: list[Path] = []
    if p is not None:
        cands += [p / ".env"]
        if p.parent.name == "workspaces":
            cands.append(p.parent / f"mamba-{p.name}" / ".env")
        try:
            git_root = p
            while git_root != git_root.parent and not (git_root / ".git").exists():
                git_root = git_root.parent
            if (git_root / ".git").exists():
                cands.append(git_root / ".env")
        except Exception:
            pass
    cands += [home / ".env"]
    seen: set[str] = set()
    uniq: list[Path] = []
    for c in cands:
        key = str(c)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


def _redact_env_line(line: str) -> str:
    """Redact secret-shaped values in a single KEY=VALUE line. Keep the
    key visible (operators need to know which env vars are set) and
    blank the value when the key looks sensitive."""
    if "=" not in line:
        return line
    key, _, value = line.partition("=")
    key_upper = key.strip().upper()
    if any(
        tag in key_upper
        for tag in ("TOKEN", "SECRET", "KEY", "PASSWORD", "PASS", "CREDENTIAL")
    ):
        return f"{key}=***REDACTED***"
    # Values that look like a JWT / long opaque token regardless of key.
    v = value.strip()
    if len(v) >= 24 and v.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return f"{key}=***REDACTED***"
    return line


def collect_orochi_env_file(workspace: str) -> str:
    """Return the workspace .env content (per-line redacted, truncated to
    10000 chars). Empty string when no .env is discoverable.

    Producer-side redaction is the first defense; the hub redacts again on
    render so a future heartbeat path that forgets still stays safe.
    """
    text = ""
    for env_path in _orochi_env_file_candidates(workspace):
        try:
            if not env_path.is_file():
                continue
            raw = env_path.read_text(errors="replace")
            redacted_lines = [_redact_env_line(ln) for ln in raw.splitlines()]
            text = "\n".join(redacted_lines)[:10000]
            break
        except Exception:
            continue
    return text
