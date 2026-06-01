"""Tests for ``_agent_container_bridge/dispatch.py``.

Covers two surfaces:

1. ``prepare_shim_yaml`` — the yaml roundtrip that injects
   ``--mcp-config`` and ``--dangerously-load-development-channels`` into
   the agent yaml's ``claude.flags`` (in the correct order).

2. The new loud-crash contract for ``_remote_home_dir`` and
   ``scp_mcp_config_to_remote`` (PR fix/dispatch-loud-crash): every
   ssh failure must raise ``RuntimeError`` carrying the real rc +
   stderr, instead of silently logging a warning and returning.

Subprocess invocations are monkey-patched (no real ssh / no remote).
This is plumbing-mocking, not behaviour-mocking — we never replace what
the code under test computes, only its OS boundary.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from scitex_orochi._agent_container_bridge import dispatch as dispatch_mod
from scitex_orochi._agent_container_bridge.dispatch import (
    _remote_home_dir,
    prepare_shim_yaml,
    scp_mcp_config_to_remote,
)
from scitex_orochi._agent_container_bridge.spec import OrochiSpec

# ---------------------------------------------------------------------------
# prepare_shim_yaml — passthrough when Orochi disabled
# ---------------------------------------------------------------------------


def test_prepare_shim_yaml_passthrough_when_disabled(tmp_path):
    """No Orochi -> return the original path unchanged, write no shim."""
    src = tmp_path / "agent.yaml"
    src.write_text(yaml.safe_dump({"metadata": {"name": "a"}, "spec": {}}))

    got = prepare_shim_yaml(src, OrochiSpec(), write_mcp_config_file=lambda **kw: None)

    assert got == src


def test_prepare_shim_yaml_no_mcp_path_still_writes_shim(tmp_path, monkeypatch):
    """Enabled but write_mcp_config_file returns None -> no flags injected,
    but a shim is still written under runtime/orochi/shim-yamls/."""
    src = tmp_path / "agent.yaml"
    src.write_text(
        yaml.safe_dump(
            {"metadata": {"name": "a"}, "spec": {"claude": {"flags": ["--keep-me"]}}}
        )
    )

    shim_root = tmp_path / "runtime" / "orochi" / "shim-yamls"

    def fake_runtime_path(pkg, *parts):
        return shim_root if parts else shim_root.parent

    monkeypatch.setattr(dispatch_mod.local_state, "runtime_path", fake_runtime_path)

    got = prepare_shim_yaml(
        src,
        OrochiSpec(enabled=True, hosts=["h"]),
        write_mcp_config_file=lambda **kw: None,
    )

    assert Path(got).parent == shim_root
    written = yaml.safe_load(Path(got).read_text())
    # No --mcp-config injected (write_mcp_config_file returned None) so
    # the original --keep-me must survive untouched.
    assert written["spec"]["claude"]["flags"] == ["--keep-me"]


# ---------------------------------------------------------------------------
# prepare_shim_yaml — flag injection order is load-bearing
# ---------------------------------------------------------------------------


def test_prepare_shim_yaml_injects_flags_in_required_order(tmp_path, monkeypatch):
    """--mcp-config MUST come BEFORE --dangerously-load-development-channels.

    From dispatch.py:78-89: the dev-channels flag references
    "server:scitex-orochi" which is only registered after --mcp-config
    parses the JSON file declaring it. Wrong order => silent channel
    registration failure.
    """
    src = tmp_path / "agent.yaml"
    src.write_text(
        yaml.safe_dump({"metadata": {"name": "agent-x"}, "spec": {"claude": {}}})
    )

    fake_mcp_path = "/tmp/mcp-agent-x.json"
    monkeypatch.setattr(
        dispatch_mod.local_state,
        "runtime_path",
        lambda pkg, *parts: (
            tmp_path / "rt" / Path(*parts) if parts else tmp_path / "rt"
        ),
    )

    got = prepare_shim_yaml(
        src,
        OrochiSpec(enabled=True, hosts=["h"]),
        write_mcp_config_file=lambda **kw: fake_mcp_path,
    )

    flags = yaml.safe_load(Path(got).read_text())["spec"]["claude"]["flags"]

    mcp_idx = next(i for i, f in enumerate(flags) if "--mcp-config" in f)
    dev_idx = next(
        i for i, f in enumerate(flags) if "--dangerously-load-development-channels" in f
    )
    assert mcp_idx < dev_idx, (
        f"--mcp-config must precede --dangerously-load-development-channels "
        f"in claude.flags; got {flags}"
    )
    assert fake_mcp_path in flags[mcp_idx]


def test_prepare_shim_yaml_dedupes_existing_flag_instances(tmp_path, monkeypatch):
    """If the yaml already has the flags, we must not append duplicates."""
    src = tmp_path / "agent.yaml"
    src.write_text(
        yaml.safe_dump(
            {
                "metadata": {"name": "a"},
                "spec": {
                    "claude": {
                        "flags": [
                            "--mcp-config /old/path.json",
                            "--dangerously-load-development-channels server:scitex-orochi",
                            "--keep-me",
                        ]
                    }
                },
            }
        )
    )

    monkeypatch.setattr(
        dispatch_mod.local_state,
        "runtime_path",
        lambda pkg, *parts: (
            tmp_path / "rt" / Path(*parts) if parts else tmp_path / "rt"
        ),
    )

    got = prepare_shim_yaml(
        src,
        OrochiSpec(enabled=True, hosts=["h"]),
        write_mcp_config_file=lambda **kw: "/tmp/new.json",
    )

    flags = yaml.safe_load(Path(got).read_text())["spec"]["claude"]["flags"]
    mcp_flags = [f for f in flags if "--mcp-config" in f]
    dev_flags = [f for f in flags if "--dangerously-load-development-channels" in f]

    assert len(mcp_flags) == 1, f"expected exactly one --mcp-config flag, got {flags}"
    assert len(dev_flags) == 1
    assert "--keep-me" in flags  # unrelated flag preserved
    assert "/tmp/new.json" in mcp_flags[0]  # new path won
    assert "/old/path.json" not in mcp_flags[0]


def test_prepare_shim_yaml_remote_triggers_scp(tmp_path, monkeypatch):
    """If ``spec.remote.host`` is set, scp_mcp_config_to_remote is invoked."""
    src = tmp_path / "agent.yaml"
    src.write_text(
        yaml.safe_dump(
            {
                "metadata": {"name": "a"},
                "spec": {
                    "remote": {"host": "spartan.example", "user": "yw"},
                    "claude": {},
                },
            }
        )
    )

    monkeypatch.setattr(
        dispatch_mod.local_state,
        "runtime_path",
        lambda pkg, *parts: (
            tmp_path / "rt" / Path(*parts) if parts else tmp_path / "rt"
        ),
    )
    scp_calls: list = []
    monkeypatch.setattr(
        dispatch_mod,
        "scp_mcp_config_to_remote",
        lambda local_path, host, section: scp_calls.append((local_path, host, section)),
    )

    prepare_shim_yaml(
        src,
        OrochiSpec(enabled=True, hosts=["h"]),
        write_mcp_config_file=lambda **kw: "/tmp/local-mcp.json",
    )

    assert len(scp_calls) == 1
    local_path, host, section = scp_calls[0]
    assert local_path == "/tmp/local-mcp.json"
    assert host == "spartan.example"
    assert section["user"] == "yw"


# ---------------------------------------------------------------------------
# _remote_home_dir — new no-fallback contract
# ---------------------------------------------------------------------------


def _fake_run(returncode=0, stdout="", stderr=""):
    """Build a fake CompletedProcess factory for monkeypatching."""

    def runner(cmd, **kw):
        return subprocess.CompletedProcess(
            args=cmd, returncode=returncode, stdout=stdout, stderr=stderr
        )

    return runner


def test_remote_home_dir_parses_last_path_line(monkeypatch):
    """A chatty bashrc can prepend noise to stdout; we pick the last /-line."""
    monkeypatch.setattr(
        dispatch_mod.subprocess,
        "run",
        _fake_run(
            stdout="Dashboard started in background\nsome warning\n/home/yw\n",
        ),
    )

    assert _remote_home_dir("yw@host", []) == "/home/yw"


def test_remote_home_dir_raises_on_nonzero_rc(monkeypatch):
    """The OLD silent-None contract is gone — non-zero rc must raise."""
    monkeypatch.setattr(
        dispatch_mod.subprocess,
        "run",
        _fake_run(returncode=255, stderr="ssh: connect to host bad port 22: refused"),
    )

    with pytest.raises(RuntimeError) as exc:
        _remote_home_dir("yw@bad", [])

    msg = str(exc.value)
    assert "rc=255" in msg
    assert "refused" in msg


def test_remote_home_dir_raises_when_no_path_line(monkeypatch):
    """rc=0 but bashrc echoed only noise (no '/' line) -> raise."""
    monkeypatch.setattr(
        dispatch_mod.subprocess,
        "run",
        _fake_run(stdout="garbled noise\n123\n"),
    )

    with pytest.raises(RuntimeError) as exc:
        _remote_home_dir("yw@host", [])

    assert "no path-like line" in str(exc.value)


def test_remote_home_dir_propagates_subprocess_timeout(monkeypatch):
    """Timeout must propagate (old contract swallowed it as None)."""

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=15)

    monkeypatch.setattr(dispatch_mod.subprocess, "run", boom)

    with pytest.raises(subprocess.TimeoutExpired):
        _remote_home_dir("yw@host", [])


# ---------------------------------------------------------------------------
# scp_mcp_config_to_remote — new no-fallback contract
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_file(tmp_path):
    p = tmp_path / "mcp-a.json"
    p.write_text('{"args":["/home/yw/ts/mcp_channel.ts"]}')
    return p


def test_scp_raises_when_remote_home_detection_fails(monkeypatch, mcp_file):
    """The very first step (detecting remote $HOME) must propagate failures.

    Old behaviour: silent fall-through with the dispatcher's home prefix
    written to the remote, leading to a wrong --mcp-config path on darwin.
    """

    def boom(*a, **kw):
        raise RuntimeError("ssh boom")

    monkeypatch.setattr(dispatch_mod, "_remote_home_dir", boom)

    with pytest.raises(RuntimeError, match="ssh boom"):
        scp_mcp_config_to_remote(str(mcp_file), "h.example", {})


def test_scp_raises_when_mkdir_returns_nonzero(monkeypatch, mcp_file):
    """Remote ``mkdir -p`` failure must raise with real stderr."""
    monkeypatch.setattr(
        dispatch_mod, "_remote_home_dir", lambda *a, **kw: str(Path.home())
    )

    calls: list = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        # First call is mkdir; return failure.
        if "mkdir" in " ".join(cmd):
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout="", stderr="permission denied"
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dispatch_mod.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc:
        scp_mcp_config_to_remote(str(mcp_file), "h.example", {})

    assert "Remote mkdir" in str(exc.value)
    assert "permission denied" in str(exc.value)


def test_scp_raises_when_transfer_returns_nonzero(monkeypatch, mcp_file):
    """The ``cat | ssh 'cat >'`` step's failure must raise."""
    monkeypatch.setattr(
        dispatch_mod, "_remote_home_dir", lambda *a, **kw: str(Path.home())
    )

    def fake_run(cmd, **kw):
        if "mkdir" in " ".join(cmd):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )
        # transfer step (cat > path)
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout=b"", stderr=b"disk full"
        )

    monkeypatch.setattr(dispatch_mod.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc:
        scp_mcp_config_to_remote(str(mcp_file), "h.example", {})

    assert "Remote write" in str(exc.value)
    assert "disk full" in str(exc.value)


def test_scp_rewrites_home_prefix_on_cross_platform_transfer(monkeypatch, mcp_file):
    """If dispatcher home != remote home, the JSON body is path-rewritten before
    the ``cat | ssh 'cat >'`` step. We capture what gets sent over."""
    dispatcher_home = str(Path.home())
    remote_home = "/Users/yw"  # darwin shape, different from dispatcher

    # The mcp_file fixture wrote /home/yw/... — make sure dispatcher_home
    # appears in the file so the rewrite has something to do.
    mcp_file.write_text(f'{{"args":["{dispatcher_home}/ts/mcp_channel.ts"]}}')

    monkeypatch.setattr(dispatch_mod, "_remote_home_dir", lambda *a, **kw: remote_home)

    captured: dict = {}

    def fake_run(cmd, **kw):
        if "mkdir" in " ".join(cmd):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )
        # Transfer: capture the input bytes piped via ``cat >``.
        captured["input"] = kw.get("input")
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=b"", stderr=b""
        )

    monkeypatch.setattr(dispatch_mod.subprocess, "run", fake_run)

    scp_mcp_config_to_remote(str(mcp_file), "darwin.example", {})

    body = captured["input"].decode("utf-8")
    assert remote_home in body
    assert dispatcher_home not in body, (
        "dispatcher home prefix leaked into remote body; cross-host paths "
        f"will 404 on the remote claude --mcp-config: {body!r}"
    )


def test_scp_skips_rewrite_when_homes_match(monkeypatch, mcp_file):
    """Same-platform case: no rewrite, raw bytes flow through."""
    home = str(Path.home())
    mcp_file.write_text(f'{{"args":["{home}/ts/mcp_channel.ts"]}}')

    monkeypatch.setattr(dispatch_mod, "_remote_home_dir", lambda *a, **kw: home)

    captured: dict = {}

    def fake_run(cmd, **kw):
        if "mkdir" in " ".join(cmd):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )
        captured["input"] = kw.get("input")
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=b"", stderr=b""
        )

    monkeypatch.setattr(dispatch_mod.subprocess, "run", fake_run)

    scp_mcp_config_to_remote(str(mcp_file), "linux.example", {})

    assert captured["input"] == mcp_file.read_bytes()
