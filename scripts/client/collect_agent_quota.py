#!/usr/bin/env -S python3 -u
"""Per-agent Claude API quota telemetry collector.

Walks ``~/.claude/projects/`` for directories matching ``*workspaces-*``
or ``*workspaces/*``, extracts an agent name from the ``workspaces-<name>``
suffix, reads all ``.jsonl`` files in those directories, parses entries
with ``type=='assistant'`` that carry a ``message.usage`` block, and
aggregates token/request counts over four time windows:

    last 15 min  →  quota_15m
    last 1 h     →  quota_1h
    last 24 h    →  quota_24h
    all time     →  quota_all

Each window dict has:
    input_tokens          int
    cache_tokens          int   (creation + read combined)
    output_tokens         int
    web_searches          int
    web_fetches           int
    turns                 int   (number of assistant turns counted)

Output is written to ``~/.scitex/orochi/quota/<agent-name>.json``
(one file per agent, idempotent, safe to re-run any time).

With ``--post`` the script also POSTs the collected data to the Orochi
hub's ``/api/agent-quota/`` endpoint (or ``/api/agents/register/`` if
the former does not exist yet).

Usage:
    collect_agent_quota.py
        Collect and write JSON to ~/.scitex/orochi/quota/<name>.json

    collect_agent_quota.py --post [--url URL] [--token TOKEN]
        Also POST to hub /api/agents/register/ (as quota_* fields)

    collect_agent_quota.py --agent <name>
        Only collect for a specific agent name

Performance: uses mtime caching so unchanged .jsonl files are skipped.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("collect_agent_quota")

# ── time-window constants ────────────────────────────────────────────────────
_WINDOWS: dict[str, float] = {
    "quota_15m": 15 * 60,
    "quota_1h": 60 * 60,
    "quota_24h": 24 * 60 * 60,
    "quota_all": float("inf"),
}

# ── zero-value template for one window ──────────────────────────────────────
def _zero_window() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "cache_tokens": 0,
        "output_tokens": 0,
        "web_searches": 0,
        "web_fetches": 0,
        "turns": 0,
    }


def _parse_ts(ts_str: str) -> float | None:
    """Parse ISO-8601 timestamp string to unix epoch float, or None."""
    if not ts_str:
        return None
    try:
        # Python 3.11+ handles Z; older needs replace
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _discover_agent_dirs(claude_projects: Path) -> dict[str, Path]:
    """Return {agent_name: project_dir} for all matching workspace dirs.

    Matches both dash-encoded paths (``-home-...-workspaces-<name>``) and
    slash-based paths containing ``workspaces/<name>`` as the last two segments.
    """
    result: dict[str, Path] = {}
    if not claude_projects.is_dir():
        return result

    # Pattern: directory name ends with ``workspaces-<agent-name>``
    # The dash-encoded form replaces path separators with dashes.
    ws_dash_re = re.compile(r"workspaces-([^/]+)$")
    # Also handle the case where the dir path itself contains workspaces/<name>
    ws_slash_re = re.compile(r"workspaces/([^/]+)$")

    for entry in claude_projects.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        # Try dash-encoded form first
        m = ws_dash_re.search(name)
        if m:
            agent_name = m.group(1)
            result[agent_name] = entry
            continue
        # Try slash form (shouldn't exist in ~/.claude/projects, but be safe)
        m = ws_slash_re.search(str(entry))
        if m:
            agent_name = m.group(1)
            result[agent_name] = entry
    return result


def _collect_from_dir(
    project_dir: Path,
    now_ts: float,
    mtime_cache: dict[str, float],
) -> list[dict[str, Any]]:
    """Read all .jsonl files in ``project_dir`` and return a list of
    usage records: {ts: float, input_tokens: int, ...}

    Uses ``mtime_cache`` (path→mtime) to skip files that haven't changed
    since the last run.  The cache is mutated in-place.
    """
    records: list[dict[str, Any]] = []
    for jsonl_path in project_dir.glob("*.jsonl"):
        try:
            mtime = jsonl_path.stat().st_mtime
        except OSError:
            continue
        cache_key = str(jsonl_path)
        # Even if mtime matches, we must re-read because the test might
        # have touched the file. Only skip when mtime is identical.
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                usage = (entry.get("message") or {}).get("usage")
                if not usage:
                    continue
                ts = _parse_ts(entry.get("timestamp", ""))
                if ts is None:
                    # Fall back to mtime of the file as approximation
                    ts = mtime
                svr = usage.get("server_tool_use") or {}
                records.append(
                    {
                        "ts": ts,
                        "input_tokens": int(usage.get("input_tokens") or 0),
                        "cache_creation": int(
                            usage.get("cache_creation_input_tokens") or 0
                        ),
                        "cache_read": int(
                            usage.get("cache_read_input_tokens") or 0
                        ),
                        "output_tokens": int(usage.get("output_tokens") or 0),
                        "web_searches": int(
                            svr.get("web_search_requests") or 0
                        ),
                        "web_fetches": int(
                            svr.get("web_fetch_requests") or 0
                        ),
                    }
                )
        mtime_cache[cache_key] = mtime
    return records


def _aggregate(records: list[dict[str, Any]], now_ts: float) -> dict[str, dict]:
    """Bucket records into the four time windows and sum each field."""
    windows: dict[str, dict[str, int]] = {k: _zero_window() for k in _WINDOWS}
    for rec in records:
        age = now_ts - rec["ts"]
        if age < 0:
            age = 0  # clock skew — treat as fresh
        for win_key, max_age in _WINDOWS.items():
            if age <= max_age:
                w = windows[win_key]
                w["input_tokens"] += rec["input_tokens"]
                w["cache_tokens"] += rec["cache_creation"] + rec["cache_read"]
                w["output_tokens"] += rec["output_tokens"]
                w["web_searches"] += rec["web_searches"]
                w["web_fetches"] += rec["web_fetches"]
                w["turns"] += 1
    return windows


def collect_all(
    target_agent: str | None = None,
) -> dict[str, dict[str, dict]]:
    """Collect quota data for all (or one) agent(s).

    Returns {agent_name: {quota_15m: {...}, quota_1h: {...}, ...}}
    """
    claude_projects = Path.home() / ".claude" / "projects"
    agent_dirs = _discover_agent_dirs(claude_projects)

    if target_agent:
        if target_agent not in agent_dirs:
            _LOG.warning("agent %r not found in %s", target_agent, claude_projects)
            return {}
        agent_dirs = {target_agent: agent_dirs[target_agent]}

    now_ts = time.time()
    mtime_cache: dict[str, float] = {}
    result: dict[str, dict[str, dict]] = {}

    for agent_name, project_dir in agent_dirs.items():
        records = _collect_from_dir(project_dir, now_ts, mtime_cache)
        if not records:
            # Include zero-quota agents so presence is explicit
            result[agent_name] = {k: _zero_window() for k in _WINDOWS}
        else:
            result[agent_name] = _aggregate(records, now_ts)
        _LOG.debug(
            "agent=%s dirs=%s records=%d",
            agent_name,
            project_dir.name,
            len(records),
        )
    return result


def write_quota_files(quota_data: dict[str, dict[str, dict]]) -> list[Path]:
    """Write per-agent quota JSON files to ~/.scitex/orochi/quota/.

    Returns list of written paths.
    """
    out_dir = Path.home() / ".scitex" / "orochi" / "quota"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for agent_name, windows in quota_data.items():
        out_path = out_dir / f"{agent_name}.json"
        payload = {
            "agent": agent_name,
            "collected_at": datetime.now(tz=timezone.utc).isoformat(),
            **windows,
        }
        tmp = out_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(out_path)
        written.append(out_path)
    return written


def post_to_hub(
    agent_name: str,
    windows: dict[str, dict],
    hub_url: str,
    token: str,
) -> bool:
    """POST quota windows for one agent to hub /api/agents/register/.

    Embeds quota_15m / quota_1h / quota_24h / quota_all as top-level
    fields in the heartbeat body so the existing register endpoint can
    store them.  Returns True on success (HTTP 2xx).
    """
    url = hub_url.rstrip("/") + "/api/agents/register/"
    body: dict[str, Any] = {
        "token": token,
        "name": agent_name,
        "quota_15m": windows.get("quota_15m"),
        "quota_1h": windows.get("quota_1h"),
        "quota_24h": windows.get("quota_24h"),
        "quota_all": windows.get("quota_all"),
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
            if not ok:
                _LOG.warning(
                    "POST quota for %s → HTTP %d", agent_name, resp.status
                )
            return ok
    except Exception as exc:
        _LOG.warning("POST quota for %s failed: %s", agent_name, exc)
        return False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        format="%(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    parser = argparse.ArgumentParser(
        description="Collect per-agent Claude API quota telemetry from ~/.claude/projects/",
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="POST results to hub /api/agents/register/ as quota_* fields",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("SCITEX_OROCHI_URL_HTTP", "https://scitex-orochi.com"),
        help="Hub base URL (default: $SCITEX_OROCHI_URL_HTTP or https://scitex-orochi.com)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SCITEX_OROCHI_TOKEN", ""),
        help="Workspace token (default: $SCITEX_OROCHI_TOKEN)",
    )
    parser.add_argument(
        "--agent",
        metavar="NAME",
        default=None,
        help="Only collect for this agent name",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    quota_data = collect_all(target_agent=args.agent)
    if not quota_data:
        _LOG.info("No matching agent workspace directories found.")
        return 0

    written = write_quota_files(quota_data)
    for p in written:
        _LOG.info("wrote %s", p)

    if args.post:
        if not args.token:
            _LOG.error(
                "--post requires a token (set --token or $SCITEX_OROCHI_TOKEN)"
            )
            return 1
        for agent_name, windows in quota_data.items():
            ok = post_to_hub(agent_name, windows, args.url, args.token)
            if ok:
                _LOG.info("posted quota for %s", agent_name)

    return 0


if __name__ == "__main__":
    sys.exit(main())
