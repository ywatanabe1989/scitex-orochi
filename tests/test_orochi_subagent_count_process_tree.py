"""Tests for process-tree based subagent counting.

The programmatic walk in
``scripts/client/_collect_agent_metadata/_process_tree.py::count_subagents_via_ps``
replaces the tmux-pane regex parse as the primary
``orochi_subagent_count`` signal (msg#16727). These tests pin:

1. psutil happy paths — 0/3 children, mixed claude+non-claude children.
2. psutil failure → fall through to pgrep.
3. pgrep failure → function returns ``-1`` so ``_collect.py`` falls
   back to the pane parser.
4. Session-registry resolution — ``find_head_pid`` walks
   ``~/.claude/sessions/*.json`` by ``cwd`` match.
5. ``_looks_like_claude`` binary detector — accepts ``claude`` argv,
   rejects bash/bun/caffeinate/unrelated-claude-* tooling.
6. End-to-end ``_collect.collect`` fallback chain: process-tree first,
   pane parser on failure, 0 if both fail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# _collect_agent_metadata lives under scripts/client/ — add to sys.path so we
# can import without an editable install.
_AGENT_META_DIR = Path(__file__).resolve().parents[1] / "scripts" / "client"
if str(_AGENT_META_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_META_DIR))

from _collect_agent_metadata import _process_tree  # noqa: E402
from _collect_agent_metadata._process_tree import (  # noqa: E402
    _looks_like_claude,
    count_subagents_via_ps,
    find_head_pid,
)

# ---------------------------------------------------------------------------
# _looks_like_claude — binary detector unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmdline, expected",
    [
        # Canonical claude-code invocation shapes.
        (["claude", "--model", "opus[1m]"], True),
        (["/usr/local/bin/claude", "--dangerously-skip-permissions"], True),
        (["/opt/homebrew/bin/claude"], True),
        # Single-string cmdline (pgrep fallback shape).
        (["claude --model opus --add-dir /workspace"], True),
        # Non-claude auxiliary descendants — all rejected.
        (["caffeinate", "-i", "-t", "300"], False),
        (["bun", "run", "/path/to/mcp_channel.ts"], False),
        (["node", "/app/index.js"], False),
        (["python3", "-c", "print('claude mentioned')"], False),
        # Shell one-liners that mention claude — not a subagent.
        (["/bin/bash", "-c", "grep claude /tmp/foo.log"], False),
        (["sh", "-c", "ps -eo command | awk '/claude/'"], False),
        # Sibling tools — NOT the claude CLI itself.
        (["claude-hud", "--poll"], False),
        (["claude-code-telegrammer", "serve"], False),
        # Empty / degenerate inputs.
        ([], False),
        ([""], False),
    ],
    ids=[
        "claude-opus",
        "claude-absolute-path",
        "claude-homebrew",
        "claude-single-string",
        "caffeinate",
        "bun",
        "node",
        "python-mentioning",
        "bash-grep",
        "sh-awk",
        "claude-hud-sibling",
        "telegrammer-sibling",
        "empty-list",
        "empty-string-arg",
    ],
)
def test_looks_like_claude(cmdline, expected):
    """The binary detector accepts only the ``claude`` CLI itself."""
    assert _looks_like_claude(cmdline) is expected


# ---------------------------------------------------------------------------
# find_head_pid — session-registry resolution
# ---------------------------------------------------------------------------


def test_find_head_pid_matches_by_cwd(tmp_path, monkeypatch):
    """``~/.claude/sessions/<pid>.json`` whose ``cwd`` matches the
    agent's workspace path IS that agent's head PID."""
    sessions = tmp_path / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    workspace_root = tmp_path / ".scitex" / "agent-container" / "workspaces"
    workspace_root.mkdir(parents=True)

    # Two sessions — one matches, one doesn't.
    (sessions / "42.json").write_text(
        json.dumps(
            {
                "pid": 42,
                "sessionId": "abc",
                "cwd": str(workspace_root / "head-mba"),
                "startedAt": 1,
            }
        )
    )
    (sessions / "99.json").write_text(
        json.dumps(
            {
                "pid": 99,
                "sessionId": "xyz",
                "cwd": str(workspace_root / "some-other-agent"),
                "startedAt": 2,
            }
        )
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert find_head_pid("head-mba") == 42


def test_find_head_pid_none_when_no_session(tmp_path, monkeypatch):
    """Missing session file → ``None`` (the caller falls back)."""
    (tmp_path / ".claude" / "sessions").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert find_head_pid("head-nonexistent") is None


def test_find_head_pid_skips_malformed_json(tmp_path, monkeypatch):
    """A junk ``<pid>.json`` doesn't crash the scan."""
    sessions = tmp_path / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    workspace_root = tmp_path / ".scitex" / "agent-container" / "workspaces"
    workspace_root.mkdir(parents=True)
    (sessions / "42.json").write_text("not json at all {{{")
    (sessions / "43.json").write_text(
        json.dumps(
            {
                "pid": 43,
                "cwd": str(workspace_root / "head-mba"),
                "startedAt": 1,
            }
        )
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert find_head_pid("head-mba") == 43


# ---------------------------------------------------------------------------
# count_subagents_via_ps — orchestrated walk with fallback chain
# ---------------------------------------------------------------------------


class _FakeProcess:
    """Minimal psutil.Process stand-in for children() / cmdline() tests."""

    def __init__(self, children=None, cmdline_value=None):
        self._children = children or []
        self._cmdline = cmdline_value or []

    def children(self, recursive=True):
        return self._children

    def cmdline(self):
        return self._cmdline


def _install_fake_psutil(monkeypatch, head_proc_factory):
    """Install a fake ``psutil`` module under the import name so that
    ``import psutil`` inside ``_process_tree`` returns our stub.

    ``head_proc_factory`` is a callable that returns the fake ``Process``
    instance for the head PID.
    """

    class _NoSuchProcess(Exception):
        pass

    class _AccessDenied(Exception):
        pass

    class _FakePsutil:
        NoSuchProcess = _NoSuchProcess
        AccessDenied = _AccessDenied

        @staticmethod
        def Process(pid):  # noqa: N802 — mirror psutil API
            return head_proc_factory(pid)

    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil)


def test_count_zero_children(monkeypatch, tmp_path):
    """Head has no descendants → count 0 (authoritative, not fallback)."""
    monkeypatch.setattr(
        _process_tree, "find_head_pid", lambda agent: 1000
    )
    _install_fake_psutil(
        monkeypatch,
        lambda pid: _FakeProcess(children=[]),
    )
    # Redirect audit log to tmp so we don't pollute the real runtime dir.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert count_subagents_via_ps("head-mba") == 0


def test_count_three_claude_children(monkeypatch, tmp_path):
    """Three ``claude`` descendants → count 3."""
    children = [
        _FakeProcess(cmdline_value=["claude", "--model", "opus[1m]"]),
        _FakeProcess(cmdline_value=["/usr/local/bin/claude", "--flag"]),
        _FakeProcess(cmdline_value=["claude"]),
    ]
    monkeypatch.setattr(
        _process_tree, "find_head_pid", lambda agent: 1000
    )
    _install_fake_psutil(
        monkeypatch,
        lambda pid: _FakeProcess(children=children),
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert count_subagents_via_ps("head-mba") == 3


def test_count_mixed_claude_and_non_claude_children(monkeypatch, tmp_path):
    """Only claude descendants are counted; bun / caffeinate / bash are filtered."""
    children = [
        _FakeProcess(cmdline_value=["claude", "--model", "opus[1m]"]),
        _FakeProcess(cmdline_value=["caffeinate", "-i", "-t", "300"]),
        _FakeProcess(cmdline_value=["bun", "run", "/mcp.ts"]),
    ]
    monkeypatch.setattr(
        _process_tree, "find_head_pid", lambda agent: 1000
    )
    _install_fake_psutil(
        monkeypatch,
        lambda pid: _FakeProcess(children=children),
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert count_subagents_via_ps("head-mba") == 1


def test_no_session_file_returns_minus_one(monkeypatch, tmp_path):
    """No matching ``<pid>.json`` → return ``-1`` so caller falls back."""
    monkeypatch.setattr(
        _process_tree, "find_head_pid", lambda agent: None
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert count_subagents_via_ps("head-mba") == -1


def test_psutil_noSuchProcess_falls_back_to_pgrep(monkeypatch, tmp_path):
    """If psutil raises NoSuchProcess (stale PID) AND pgrep succeeds,
    the pgrep count wins."""

    class _NoSuchProcess(Exception):
        pass

    class _AccessDenied(Exception):
        pass

    class _FakePsutil:
        NoSuchProcess = _NoSuchProcess
        AccessDenied = _AccessDenied

        @staticmethod
        def Process(pid):  # noqa: N802
            raise _NoSuchProcess("dead")

    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil)
    monkeypatch.setattr(
        _process_tree, "find_head_pid", lambda agent: 1000
    )
    # Short-circuit pgrep path — return 2 authoritatively.
    monkeypatch.setattr(
        _process_tree,
        "_count_claude_descendants_pgrep",
        lambda pid: 2,
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert count_subagents_via_ps("head-mba") == 2


def test_both_backends_fail_returns_minus_one(monkeypatch, tmp_path):
    """psutil unavailable + pgrep walk failed → ``-1`` so ``_collect.py``
    falls back to the pane parser."""
    # Hide psutil so the psutil path returns -1.
    monkeypatch.setitem(sys.modules, "psutil", None)

    monkeypatch.setattr(
        _process_tree, "find_head_pid", lambda agent: 1000
    )
    monkeypatch.setattr(
        _process_tree,
        "_count_claude_descendants_pgrep",
        lambda pid: -1,
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert count_subagents_via_ps("head-mba") == -1


# ---------------------------------------------------------------------------
# Integration — _collect.py fallback chain end to end
# ---------------------------------------------------------------------------


def test_collect_prefers_process_tree_over_pane_parser(monkeypatch):
    """``_collect.collect`` uses the process-tree count when it's
    non-negative, even when the pane marker says something different."""
    from _collect_agent_metadata import _collect

    # Make the pane parser return 5 (lie). Process-tree returns 1.
    # _collect must surface 1, not 5.
    monkeypatch.setattr(_collect, "detect_multiplexer", lambda a: "tmux")
    monkeypatch.setattr(_collect, "capture_pane", lambda a, m: "fake pane")
    monkeypatch.setattr(
        _collect,
        "filter_orochi_pane_tail",
        lambda p: ("", "", "", ""),
    )
    monkeypatch.setattr(
        _collect,
        "parse_orochi_subagent_count",
        lambda p: 5,
    )
    monkeypatch.setattr(
        _collect,
        "count_subagents_via_ps",
        lambda a: 1,
    )
    # Neutralise the heavier collectors so the test stays focused.
    _neutralise_heavy_collectors(monkeypatch, _collect)

    result = _collect.collect("head-mba")
    assert result["orochi_subagent_count"] == 1
    assert result["subagents"] == 1


def test_collect_falls_back_to_pane_parser_on_process_tree_failure(monkeypatch):
    """When the process-tree walk returns ``-1``, ``_collect.collect``
    uses the pane parser's count."""
    from _collect_agent_metadata import _collect

    monkeypatch.setattr(_collect, "detect_multiplexer", lambda a: "tmux")
    monkeypatch.setattr(_collect, "capture_pane", lambda a, m: "pane text")
    monkeypatch.setattr(
        _collect,
        "filter_orochi_pane_tail",
        lambda p: ("", "", "", ""),
    )
    monkeypatch.setattr(
        _collect,
        "parse_orochi_subagent_count",
        lambda p: 4,
    )
    monkeypatch.setattr(
        _collect,
        "count_subagents_via_ps",
        lambda a: -1,
    )
    _neutralise_heavy_collectors(monkeypatch, _collect)

    result = _collect.collect("head-mba")
    assert result["orochi_subagent_count"] == 4


def test_collect_reports_zero_when_both_backends_fail(monkeypatch):
    """Process-tree returns ``-1`` AND pane parser returns 0 → ``orochi_subagent_count == 0``."""
    from _collect_agent_metadata import _collect

    monkeypatch.setattr(_collect, "detect_multiplexer", lambda a: "tmux")
    monkeypatch.setattr(_collect, "capture_pane", lambda a, m: "")
    monkeypatch.setattr(
        _collect,
        "filter_orochi_pane_tail",
        lambda p: ("", "", "", ""),
    )
    monkeypatch.setattr(
        _collect,
        "parse_orochi_subagent_count",
        lambda p: 0,
    )
    monkeypatch.setattr(
        _collect,
        "count_subagents_via_ps",
        lambda a: -1,
    )
    _neutralise_heavy_collectors(monkeypatch, _collect)

    result = _collect.collect("head-mba")
    assert result["orochi_subagent_count"] == 0


def _neutralise_heavy_collectors(monkeypatch, _collect):
    """Stub out the non-count collectors so the integration tests stay
    deterministic and don't hit the filesystem / subprocess heavy paths.
    """
    monkeypatch.setattr(
        _collect,
        "parse_statusline",
        lambda orochi_pane_tail_block: {
            "statusline_orochi_context_pct": None,
            "quota_5h_pct": None,
            "quota_5h_remaining": None,
            "quota_weekly_pct": None,
            "quota_weekly_remaining": None,
            "orochi_statusline_model": "",
            "orochi_account_email": "",
        },
    )
    monkeypatch.setattr(
        _collect,
        "find_jsonl_transcripts",
        lambda ws: [],
    )
    monkeypatch.setattr(
        _collect,
        "parse_transcript",
        lambda jsonls: {
            "model": "",
            "last_activity": "",
            "orochi_context_pct": None,
            "orochi_current_tool": "",
            "started_at": "",
            "recent_actions": [],
        },
    )
    monkeypatch.setattr(
        _collect,
        "find_session_pids",
        lambda a, m: (0, 0),
    )
    monkeypatch.setattr(
        _collect,
        "collect_orochi_skills_loaded",
        lambda ws: [],
    )
    monkeypatch.setattr(
        _collect,
        "collect_orochi_mcp_servers",
        lambda ws: [],
    )
    monkeypatch.setattr(
        _collect,
        "resolve_machine_label",
        lambda: "mba",
    )
    monkeypatch.setattr(
        _collect,
        "collect_orochi_claude_md",
        lambda ws: ("", ""),
    )
    monkeypatch.setattr(
        _collect,
        "collect_orochi_mcp_json",
        lambda ws: "",
    )
    monkeypatch.setattr(
        _collect,
        "_classify_orochi_pane_state",
        lambda *a, **kw: "online",
    )
    monkeypatch.setattr(
        _collect,
        "_extract_stuck_prompt",
        lambda *a, **kw: "",
    )
    monkeypatch.setattr(
        _collect,
        "_detect_contradiction",
        lambda *a, **kw: "",
    )
    monkeypatch.setattr(
        _collect,
        "_log_contradiction_evidence",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        _collect,
        "_resolve_canonical_hostname",
        lambda: "mba.local",
    )
    monkeypatch.setattr(
        _collect,
        "_collect_hook_events",
        lambda a: {},
    )
    monkeypatch.setattr(
        _collect,
        "collect_machine_metrics",
        lambda: {},
    )
    monkeypatch.setattr(
        _collect,
        "collect_slurm_status",
        lambda: None,
    )


# ---------------------------------------------------------------------------
# Lifecycle mirror — process-tree counts should agree with spawn /
# partial / complete transitions (extend PR #333 coverage).
# ---------------------------------------------------------------------------


def test_lifecycle_spawn_then_complete(monkeypatch, tmp_path):
    """Tick 1: 1 claude descendant. Tick 2: 0 (batch finished)."""
    monkeypatch.setattr(
        _process_tree, "find_head_pid", lambda agent: 1000
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    # Tick 1 — one child claude.
    _install_fake_psutil(
        monkeypatch,
        lambda pid: _FakeProcess(
            children=[_FakeProcess(cmdline_value=["claude", "--flag"])]
        ),
    )
    assert count_subagents_via_ps("head-mba") == 1

    # Tick 2 — no children.
    _install_fake_psutil(
        monkeypatch,
        lambda pid: _FakeProcess(children=[]),
    )
    assert count_subagents_via_ps("head-mba") == 0


def test_lifecycle_partial_completion(monkeypatch, tmp_path):
    """Three spawned, one finished → process-tree count 2."""
    monkeypatch.setattr(
        _process_tree, "find_head_pid", lambda agent: 1000
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    _install_fake_psutil(
        monkeypatch,
        lambda pid: _FakeProcess(
            children=[
                _FakeProcess(cmdline_value=["claude", "--flag"]),
                _FakeProcess(cmdline_value=["claude", "--flag2"]),
            ]
        ),
    )
    assert count_subagents_via_ps("head-mba") == 2


def test_audit_log_written(monkeypatch, tmp_path):
    """Every call appends one NDJSON record to the audit log."""
    monkeypatch.setattr(
        _process_tree, "find_head_pid", lambda agent: 1000
    )
    _install_fake_psutil(
        monkeypatch,
        lambda pid: _FakeProcess(
            children=[_FakeProcess(cmdline_value=["claude"])]
        ),
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    assert count_subagents_via_ps("head-mba") == 1

    log_file = (
        tmp_path
        / ".scitex"
        / "orochi"
        / "runtime"
        / "subagent-count"
        / "head-mba.ndjson"
    )
    assert log_file.exists()
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["agent"] == "head-mba"
    assert record["count"] == 1
    assert record["source"] == "process_tree_psutil"
    assert record["head_pid"] == 1000
