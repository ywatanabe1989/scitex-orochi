"""Process-tree based subagent detection (replaces tmux-pane regex parse).

Rationale
---------
The legacy ``_pane.parse_orochi_subagent_count`` regex-scans the tmux pane for
Claude Code's status-line marker ``N local agent(s) running``. That path
has two known failure modes:

1. **Chat-embedded quotes** — prose quoting the literal marker phrase
   (help text, channel citations) false-positively matches and inflates
   the count (``test_orochi_subagent_count_lifecycle.test_quoted_marker_phrase_false_positive``
   — pinned as ``xfail`` in PR #333).
2. **Status-line invisibility** — if Claude Code suppresses or rewords
   the marker in a future release, the parser silently floors to zero
   while subagents are actually live. The auto-dispatch pipeline
   (PR #334) then misfires because ``orochi_subagent_count == 0`` is its
   "head is idle" trigger.

This module counts subagents **programmatically** by walking the
process tree:

- Each head/worker agent is a top-level ``claude`` process spawned by
  a tmux launcher. Its PID is discoverable via ``~/.claude/sessions/<pid>.json``
  whose ``cwd`` matches ``~/.scitex/agent-container/workspaces/<agent>``.
- When the head invokes the ``Agent()`` tool, Claude Code spawns a
  **separate ``claude`` subprocess** as a descendant of the head's PID.
- The count of descendant ``claude`` processes IS the subagent count.

Auxiliary descendants (bun MCP sidecar, caffeinate, bash one-shots
like ``pgrep``) are filtered out by requiring ``claude`` in the
cmdline — they never match.

Fallback chain
--------------
1. ``psutil`` children walk (preferred — cross-platform, rich metadata).
2. ``pgrep -P`` recursive walk (Linux/macOS stdlib).
3. Returns ``-1`` on total failure so the caller can fall back to
   ``_pane.parse_orochi_subagent_count``. A zero here means "we walked and
   found zero descendants" — an authoritative zero, not a failure.

The wire-in in ``_collect.py`` composes this with the pane parser:
process-tree first, pane parser on failure, ``0`` if both fail.

Audit log
---------
Each invocation appends a structured NDJSON record to
``~/.scitex/orochi/runtime/subagent-count/<agent>.ndjson`` with the
source (``process_tree``, ``pane_parser``, ``none``) and the count. The
hub can diff sources over time to flag regressions ("pane says 3,
process-tree says 0 — which is real?") without operators having to
scrape logs by hand.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Agent -> head Claude PID resolution
# ---------------------------------------------------------------------------


def _sessions_dir() -> Path:
    """Return ``~/.claude/sessions``.

    Claude Code writes one ``<pid>.json`` per live session here, each
    carrying ``{pid, sessionId, cwd, startedAt, ...}``. Walking this
    directory is how we associate an agent name to its claude PID
    without parsing tmux (the multiplexer is orthogonal to the session
    registry).
    """
    return Path.home() / ".claude" / "sessions"


def _workspace_for(agent: str) -> str:
    """Return the canonical workspace path for ``agent``.

    Matches the ``cwd`` field inside the Claude session registry so we
    can resolve ``agent -> pid`` by path equality without pulling the
    rest of the fleet config.
    """
    return str(
        Path.home() / ".scitex" / "agent-container" / "workspaces" / agent
    )


def find_head_pid(agent: str) -> Optional[int]:
    """Return the live Claude PID for ``agent`` via the session registry.

    Returns ``None`` if no matching session file exists (agent not
    running, or the registry hasn't caught up yet — sessions are
    written at claude spawn and deleted on exit).

    Matching is by ``cwd`` equality against ``workspaces/<agent>``; a
    single agent can legitimately have only one live session, so the
    first match wins. In the rare stale-file case (crashed claude that
    left a ``<pid>.json`` behind) the PID will fail to resolve later
    in the walk and the function's caller naturally falls back.
    """
    sess_dir = _sessions_dir()
    if not sess_dir.is_dir():
        return None
    workspace = _workspace_for(agent)
    for entry in sess_dir.iterdir():
        if entry.suffix != ".json":
            continue
        try:
            data = json.loads(entry.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("cwd", "")).rstrip("/") == workspace.rstrip("/"):
            pid = data.get("pid")
            if isinstance(pid, int) and pid > 0:
                return pid
    return None


# ---------------------------------------------------------------------------
# Claude-descendant counting — psutil preferred, pgrep fallback
# ---------------------------------------------------------------------------


def _count_claude_descendants_psutil(head_pid: int) -> int:
    """Return the number of descendant claude processes of ``head_pid`` via psutil.

    Returns ``-1`` if psutil is unavailable or the PID is already gone;
    the caller distinguishes "authoritative 0 descendants" from
    "couldn't walk" by checking the sign.
    """
    try:
        import psutil  # type: ignore
    except ImportError:
        return -1
    try:
        head = psutil.Process(head_pid)
    except psutil.NoSuchProcess:
        return -1
    except Exception:
        return -1
    count = 0
    try:
        for child in head.children(recursive=True):
            try:
                cmdline = child.cmdline()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
            if _looks_like_claude(cmdline):
                count += 1
    except psutil.NoSuchProcess:
        return -1
    except Exception:
        return -1
    return count


def _count_claude_descendants_pgrep(head_pid: int) -> int:
    """Return the number of descendant claude processes via ``pgrep``.

    Walks the tree level-by-level with ``pgrep -P <pid>`` because
    neither POSIX nor GNU pgrep has a recursive flag. Each candidate
    PID is re-inspected with ``ps`` so we can match on the command
    line (filtering out bun, bash, caffeinate — they're children of
    claude too but aren't subagents).

    Returns ``-1`` on pgrep invocation failure (binary missing, PID
    doesn't exist at all). An empty walk returns ``0``.
    """
    # Verify the head PID exists at all — ``pgrep -P`` against a dead
    # PID returns empty, which is indistinguishable from "head exists
    # but has no children". We want to surface "walk failed" distinctly
    # so the caller can fall back.
    try:
        os.kill(head_pid, 0)
    except ProcessLookupError:
        return -1
    except PermissionError:
        # Process exists but we can't signal it — walk is still OK.
        pass
    except Exception:
        return -1

    to_visit = [head_pid]
    descendants: list[int] = []
    # Bound the walk at 10_000 nodes — pathological cycles shouldn't
    # hang the heartbeat. Real agent trees are <20 nodes.
    max_nodes = 10_000
    while to_visit and len(descendants) < max_nodes:
        parent = to_visit.pop()
        try:
            result = subprocess.run(
                ["pgrep", "-P", str(parent)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # pgrep missing entirely → can't walk; tell caller so it
            # falls back to the pane parser.
            if parent == head_pid and not descendants:
                return -1
            # Partial walk is fine — just stop descending this branch.
            continue
        except Exception:
            continue
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                child_pid = int(line)
            except ValueError:
                continue
            descendants.append(child_pid)
            to_visit.append(child_pid)

    if not descendants:
        return 0

    # Single ps invocation to fetch cmdlines for all descendants.
    try:
        ps_out = subprocess.run(
            ["ps", "-o", "pid=,command="] + ["-p"] + [str(p) for p in descendants],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1
    except Exception:
        return -1

    count = 0
    for line in ps_out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # ``pid command with args`` — split on first whitespace.
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        cmdline = parts[1]
        if _looks_like_claude([cmdline]):
            count += 1
    return count


_SHELL_BASENAMES = frozenset({"bash", "sh", "zsh", "fish", "dash", "ksh"})


def _looks_like_claude(cmdline: list[str]) -> bool:
    """Return True if ``cmdline`` is a ``claude`` CLI invocation.

    ``cmdline`` is the argv list as returned by ``psutil.Process.cmdline()``
    or, in the pgrep fallback, a single-string wrapped in a one-element
    list (from ``ps -o command=``).

    Detection strategy: look at argv[0]'s basename. If it's exactly
    ``claude`` (the CLI binary), accept. Everything else — caffeinate,
    bun, node, python, bash one-liners that happen to mention "claude",
    sibling tools like ``claude-hud`` or ``claude-code-telegrammer`` —
    is rejected. We do NOT attempt to pin the ``Agent()`` spawn flags:
    by construction any ``claude``-binary descendant of the head's PID
    is a subagent (the head has no other reason to fork ``claude``).

    The single-string cmdline case (``"claude --model opus ..."``) is
    handled by splitting on whitespace before the basename check.
    """
    if not cmdline:
        return False
    head = cmdline[0]
    # Flatten the "single string with spaces" shape (pgrep fallback
    # yields this) before the basename check.
    if len(cmdline) == 1 and " " in head:
        head = head.split(None, 1)[0]
    base = os.path.basename(head).lower()
    # Skip shell wrappers — they show up as children of claude (the
    # head's Bash-tool invocations, our own ``pgrep`` shell-out) but
    # are not subagents.
    if base in _SHELL_BASENAMES:
        return False
    return base == "claude"


# ---------------------------------------------------------------------------
# Public API — the orchestrated walk with fallback
# ---------------------------------------------------------------------------


def count_subagents_via_ps(agent: str) -> int:
    """Return the subagent count for ``agent`` via process-tree inspection.

    Returns ``-1`` on total failure (agent PID unknown, both psutil
    and pgrep walks failed). The caller (``_collect.py``) treats
    ``-1`` as "fall back to the pane parser"; a non-negative value is
    authoritative.

    Contract:

    - ``0``  — head has no live claude descendants. (Authoritative.)
    - ``N``  — head has exactly N live claude descendants.
    - ``-1`` — the walk failed; caller should fall back.
    """
    head_pid = find_head_pid(agent)
    if head_pid is None:
        _audit_log(agent, -1, source="none", head_pid=None, note="no_session_file")
        return -1

    # Preferred backend: psutil.
    ps_count = _count_claude_descendants_psutil(head_pid)
    if ps_count >= 0:
        _audit_log(agent, ps_count, source="process_tree_psutil", head_pid=head_pid)
        return ps_count

    # Secondary backend: pgrep.
    pg_count = _count_claude_descendants_pgrep(head_pid)
    if pg_count >= 0:
        _audit_log(agent, pg_count, source="process_tree_pgrep", head_pid=head_pid)
        return pg_count

    _audit_log(agent, -1, source="none", head_pid=head_pid, note="walk_failed")
    return -1


# ---------------------------------------------------------------------------
# Audit log — structured NDJSON so operators can diff sources.
# ---------------------------------------------------------------------------


def _audit_log_path(agent: str) -> Path:
    """Return the NDJSON audit-log path for ``agent``.

    Stored under the standard runtime root so telemetry-rotate.sh
    picks it up (daily gzip + 7d retention, same lifecycle as the
    connection and quota telemetry files).
    """
    root = (
        Path.home()
        / ".scitex"
        / "orochi"
        / "runtime"
        / "subagent-count"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{agent}.ndjson"


def _audit_log(
    agent: str,
    count: int,
    *,
    source: str,
    head_pid: Optional[int],
    note: str = "",
) -> None:
    """Append one NDJSON record describing this count's provenance.

    Best-effort — a write failure must NOT break heartbeat collection.
    """
    try:
        payload = {
            "ts": time.time(),
            "agent": agent,
            "count": count,
            "source": source,
            "head_pid": head_pid,
        }
        if note:
            payload["note"] = note
        path = _audit_log_path(agent)
        with path.open("a") as f:
            f.write(json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:
        # Never let audit logging break the heartbeat.
        pass
