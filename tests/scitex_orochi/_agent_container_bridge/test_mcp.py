"""Tests for ``_agent_container_bridge/mcp.py``.

Covers the MCP config builder that scitex-orochi generates for each
agent's claude process. This is the surface that:

- resolves ``mcp_channel.ts`` via a 4-level fallback chain
- resolves the auth token via a 3-level fallback chain
  (per-agent env -> os.environ -> bash login shell)
- assembles the ``mcpServers.scitex-orochi`` JSON the agent's claude
  loads via ``--mcp-config``

The token-resolution helper shells out to ``bash -l -c`` as the last
resort. That branch is exercised by monkey-patching ``subprocess.run``
rather than actually shelling out (CI has no guaranteed bash login
profile).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scitex_orochi._agent_container_bridge import mcp as mcp_mod
from scitex_orochi._agent_container_bridge.mcp import (
    build_orochi_mcp_config,
    find_mcp_channel_ts,
    write_mcp_config_file,
)
from scitex_orochi._agent_container_bridge.spec import OrochiSpec

# ---------------------------------------------------------------------------
# find_mcp_channel_ts — 4-level fallback chain
# ---------------------------------------------------------------------------


def test_find_ts_explicit_path_wins(tmp_path, monkeypatch):
    """An explicit ts_path that exists on disk short-circuits everything."""
    explicit = tmp_path / "explicit.ts"
    explicit.write_text("// fake")
    # Even with a competing env var set, explicit must win.
    other = tmp_path / "env.ts"
    other.write_text("// fake")
    monkeypatch.setenv("SCITEX_OROCHI_PUSH_TS", str(other))

    got = find_mcp_channel_ts(str(explicit))

    assert got == str(explicit)


def test_find_ts_explicit_missing_falls_through_to_env(tmp_path, monkeypatch):
    """If the explicit path doesn't exist, we don't crash — we fall through."""
    explicit = tmp_path / "does-not-exist.ts"
    env_ts = tmp_path / "env.ts"
    env_ts.write_text("// fake")
    monkeypatch.setenv("SCITEX_OROCHI_PUSH_TS", str(env_ts))

    got = find_mcp_channel_ts(str(explicit))

    assert got == str(env_ts)


def test_find_ts_env_path(tmp_path, monkeypatch):
    """No explicit -> SCITEX_OROCHI_PUSH_TS picked up."""
    env_ts = tmp_path / "env.ts"
    env_ts.write_text("// fake")
    monkeypatch.setenv("SCITEX_OROCHI_PUSH_TS", str(env_ts))

    got = find_mcp_channel_ts("")

    assert got == str(env_ts)


def test_find_ts_returns_none_when_no_candidate_resolves(monkeypatch, tmp_path):
    """Nothing explicit, env unset, no package layout, no /opt path."""
    monkeypatch.delenv("SCITEX_OROCHI_PUSH_TS", raising=False)
    # Bend the package-layout fallback to a directory that has no
    # ``ts/mcp_channel.ts`` sibling.
    isolated_pkg = tmp_path / "fake_pkg" / "scitex_orochi" / "__init__.py"
    isolated_pkg.parent.mkdir(parents=True)
    isolated_pkg.write_text("")
    fake_mod = SimpleNamespace(__file__=str(isolated_pkg))
    monkeypatch.setitem(__import__("sys").modules, "scitex_orochi", fake_mod)

    got = find_mcp_channel_ts("")

    # /opt path is the last fallback and presumably absent in test env;
    # if the dev box has one we'd see that path back. Accept either
    # the real /opt path (skip) or None for a clean CI box.
    if got is not None:
        assert got == "/opt/scitex-orochi/ts/mcp_channel.ts"


# ---------------------------------------------------------------------------
# _resolve_token — 3-level fallback chain
# ---------------------------------------------------------------------------


def test_resolve_token_from_agent_env_wins(monkeypatch):
    """Per-agent token in spec.env takes precedence over everything."""
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "from-os-env")
    spec = OrochiSpec(token_env="SCITEX_OROCHI_TOKEN")
    agent_env = {"SCITEX_OROCHI_TOKEN": "from-agent-env"}

    got = mcp_mod._resolve_token(spec, agent_env)

    assert got == "from-agent-env"


def test_resolve_token_from_os_environ(monkeypatch):
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "from-os-env")
    spec = OrochiSpec(token_env="SCITEX_OROCHI_TOKEN")

    got = mcp_mod._resolve_token(spec, {})

    assert got == "from-os-env"


def test_resolve_token_bash_fallback_success(monkeypatch):
    """When neither dict has the token, we shell out to ``bash -l``."""
    monkeypatch.delenv("SCITEX_OROCHI_TOKEN", raising=False)
    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="bash-fallback-token\n",
            stderr="",
        )

    monkeypatch.setattr(mcp_mod.subprocess, "run", fake_run)

    spec = OrochiSpec(token_env="SCITEX_OROCHI_TOKEN")
    got = mcp_mod._resolve_token(spec, {})

    assert got == "bash-fallback-token"
    assert captured["cmd"][0] == "bash"
    assert "-l" in captured["cmd"]
    assert "echo $SCITEX_OROCHI_TOKEN" in captured["cmd"][-1]


def test_resolve_token_bash_fallback_empty_returns_empty_string(monkeypatch):
    """Empty bash output isn't a failure — caller treats "" as "no token"."""
    monkeypatch.delenv("SCITEX_OROCHI_TOKEN", raising=False)

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="\n", stderr=""
        )

    monkeypatch.setattr(mcp_mod.subprocess, "run", fake_run)

    got = mcp_mod._resolve_token(OrochiSpec(), {})

    assert got == ""


def test_resolve_token_bash_fallback_raises_is_swallowed(monkeypatch):
    """``bash -l`` failure must not crash the whole config build."""
    monkeypatch.delenv("SCITEX_OROCHI_TOKEN", raising=False)

    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=10)

    monkeypatch.setattr(mcp_mod.subprocess, "run", fake_run)

    got = mcp_mod._resolve_token(OrochiSpec(), {})

    assert got == ""


# ---------------------------------------------------------------------------
# build_orochi_mcp_config — assembled JSON
# ---------------------------------------------------------------------------


def test_build_returns_none_when_not_enabled():
    """An ``OrochiSpec()`` with ``enabled=False`` short-circuits."""
    got = build_orochi_mcp_config(
        agent_name="a", orochi=OrochiSpec(), agent_env={}, agent_labels={}
    )
    assert got is None


def test_build_returns_none_when_ts_bridge_missing(monkeypatch):
    """Enabled spec + no ts file -> warning + None (caller skips flag)."""
    monkeypatch.setattr(mcp_mod, "find_mcp_channel_ts", lambda _: None)
    spec = OrochiSpec(enabled=True, hosts=["h"])

    got = build_orochi_mcp_config(
        agent_name="a", orochi=spec, agent_env={}, agent_labels={}
    )

    assert got is None


def test_build_assembles_full_config(monkeypatch, tmp_path):
    """Happy path: returns the documented ``{mcpServers.scitex-orochi: ...}`` shape."""
    ts = tmp_path / "mcp_channel.ts"
    ts.write_text("// fake")
    monkeypatch.setattr(mcp_mod, "find_mcp_channel_ts", lambda _: str(ts))
    monkeypatch.delenv("SCITEX_OROCHI_TOKEN", raising=False)

    # Suppress bash fallback in _resolve_token so we get the no-token branch.
    monkeypatch.setattr(
        mcp_mod.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            args=a[0] if a else [], returncode=0, stdout="", stderr=""
        ),
    )

    spec = OrochiSpec(
        enabled=True, hosts=["primary.example", "secondary.example"], port=8559
    )
    got = build_orochi_mcp_config(
        agent_name="proj-agent-x",
        orochi=spec,
        agent_env={},
        agent_labels={},
    )

    assert got is not None
    assert "mcpServers" in got
    server = got["mcpServers"]["scitex-orochi"]
    assert server["type"] == "stdio"
    assert server["command"] == "bun"
    assert server["args"] == [str(ts)]
    env = server["env"]
    # First reachable host wins.
    assert env["SCITEX_OROCHI_HOST"] == "primary.example"
    assert env["SCITEX_OROCHI_PORT"] == "8559"
    assert env["SCITEX_OROCHI_AGENT"] == "proj-agent-x"
    # Telegram-guard defuse: empty string, not absent.
    assert env["SCITEX_OROCHI_TELEGRAM_BOT_TOKEN"] == ""
    # Role default: empty.
    assert env["SCITEX_OROCHI_AGENT_ROLE"] == ""
    # No token branch -> key is absent (not empty string).
    assert "SCITEX_OROCHI_TOKEN" not in env


def test_build_includes_token_when_resolvable(monkeypatch, tmp_path):
    ts = tmp_path / "ts"
    ts.write_text("// fake")
    monkeypatch.setattr(mcp_mod, "find_mcp_channel_ts", lambda _: str(ts))

    spec = OrochiSpec(enabled=True, hosts=["h"], token_env="MY_TOK")
    got = build_orochi_mcp_config(
        agent_name="a",
        orochi=spec,
        agent_env={"MY_TOK": "shhh"},
        agent_labels={},
    )

    assert got["mcpServers"]["scitex-orochi"]["env"]["SCITEX_OROCHI_TOKEN"] == "shhh"


@pytest.mark.parametrize(
    "labels, expected",
    [
        # (labels, (icon_env, icon_emoji_env, icon_text_env))
        # SCITEX_OROCHI_ICON chain (mcp.py:157-161) = icon-image OR icon-emoji
        # OR labels['icon'] OR env['SCITEX_OROCHI_ICON']. icon-text does NOT
        # feed SCITEX_OROCHI_ICON — it only sets SCITEX_OROCHI_ICON_TEXT.
        ({"icon-image": "img.png"}, ("img.png", None, None)),
        ({"icon-emoji": "🐍"}, ("🐍", "🐍", None)),
        ({"icon-text": "AG"}, (None, None, "AG")),
        (
            {"icon-image": "img.png", "icon-emoji": "🐍", "icon-text": "AG"},
            ("img.png", "🐍", "AG"),
        ),
        ({}, (None, None, None)),
    ],
)
def test_build_icon_precedence(monkeypatch, tmp_path, labels, expected):
    """icon-image > icon-emoji > labels['icon'] > SCITEX_OROCHI_ICON env.

    Pinning the actual chain (mcp.py:157-161): icon-text is NOT a
    fallback into SCITEX_OROCHI_ICON; it's a separate env key.
    """
    ts = tmp_path / "ts"
    ts.write_text("// fake")
    monkeypatch.setattr(mcp_mod, "find_mcp_channel_ts", lambda _: str(ts))
    monkeypatch.delenv("SCITEX_OROCHI_ICON", raising=False)

    spec = OrochiSpec(enabled=True, hosts=["h"])
    got = build_orochi_mcp_config(
        agent_name="a", orochi=spec, agent_env={}, agent_labels=labels
    )
    env = got["mcpServers"]["scitex-orochi"]["env"]
    icon_exp, emoji_exp, text_exp = expected

    assert env.get("SCITEX_OROCHI_ICON") == icon_exp
    assert env.get("SCITEX_OROCHI_ICON_EMOJI") == emoji_exp
    assert env.get("SCITEX_OROCHI_ICON_TEXT") == text_exp


# ---------------------------------------------------------------------------
# write_mcp_config_file — disk side-effect
# ---------------------------------------------------------------------------


def test_write_returns_none_when_not_enabled():
    got = write_mcp_config_file(
        agent_name="a", orochi=OrochiSpec(), agent_env={}, agent_labels={}
    )
    assert got is None


def test_write_creates_file_and_returns_path(monkeypatch, tmp_path):
    """Verify the file lands at the documented path layout under runtime/."""
    ts = tmp_path / "ts"
    ts.write_text("// fake")
    monkeypatch.setattr(mcp_mod, "find_mcp_channel_ts", lambda _: str(ts))

    out_dir = tmp_path / "runtime" / "orochi" / "mcp-configs"
    monkeypatch.setattr(
        mcp_mod.local_state,
        "runtime_path",
        lambda pkg, *parts: out_dir if parts else out_dir.parent,
    )

    spec = OrochiSpec(enabled=True, hosts=["h"])
    got = write_mcp_config_file(
        agent_name="proj-agent-y",
        orochi=spec,
        agent_env={},
        agent_labels={},
    )

    assert got == str(out_dir / "mcp-proj-agent-y.json")
    written = json.loads(Path(got).read_text())
    assert (
        written["mcpServers"]["scitex-orochi"]["env"]["SCITEX_OROCHI_AGENT"]
        == "proj-agent-y"
    )
