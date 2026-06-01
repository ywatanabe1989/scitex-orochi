"""Tests for ``_agent_container_bridge/dispatch.py``.

Compliant with scitex-dev linter:
- STX-NM001/2/3: no mock/monkeypatch/patch/Mock anywhere.
- STX-TQ002: every test carries Arrange/Act/Assert markers.
- STX-TQ007: every test asserts exactly one claim.

Real-collaborator strategy (per ``02_package/12_no-mocks.md``):

- ssh subprocess: ``ssh_shim`` drops a real fake ``ssh`` binary on
  ``$PATH``. Production ``subprocess.run(["ssh", ...])`` invokes the
  fake; assertions read ``ctrl.calls()`` / ``ctrl.stdins()``.
- ``scp_mcp_config_to_remote`` injection: ``prepare_shim_yaml`` exposes
  ``scp_fn`` as a kwarg (production default = real function). Tests
  pass a hand-rolled ``FakeScp`` dataclass that records its calls.
- ``local_state.runtime_path``: ``isolated_runtime_root`` redirects
  via ``SCITEX_DIR`` + cd, with no patching.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitex_orochi._agent_container_bridge.dispatch import (
    _remote_home_dir,
    prepare_shim_yaml,
    scp_mcp_config_to_remote,
)
from scitex_orochi._agent_container_bridge.spec import OrochiSpec

from .conftest import FakeScp

# ---------------------------------------------------------------------------
# prepare_shim_yaml — passthrough when disabled
# ---------------------------------------------------------------------------


def test_prepare_shim_yaml_passthrough_when_orochi_disabled(tmp_path):
    """No Orochi -> return the original path unchanged."""
    # Arrange
    src = tmp_path / "agent.yaml"
    src.write_text(yaml.safe_dump({"metadata": {"name": "a"}, "spec": {}}))
    # Act
    got = prepare_shim_yaml(src, OrochiSpec(), write_mcp_config_file=lambda **kw: None)
    # Assert
    assert got == src


def test_prepare_shim_yaml_writes_shim_under_runtime_root(
    tmp_path, isolated_runtime_root
):
    """Enabled but no mcp_path: a shim still lands under runtime root."""
    # Arrange
    src = tmp_path / "agent.yaml"
    src.write_text(
        yaml.safe_dump(
            {"metadata": {"name": "a"}, "spec": {"claude": {"flags": ["--keep-me"]}}}
        )
    )
    # Act
    got = prepare_shim_yaml(
        src,
        OrochiSpec(enabled=True, hosts=["h"]),
        write_mcp_config_file=lambda **kw: None,
    )
    # Assert
    assert str(got).startswith(str(isolated_runtime_root))


def test_prepare_shim_yaml_no_mcp_path_preserves_existing_flags(
    tmp_path, isolated_runtime_root
):
    """No mcp_path -> caller's existing ``claude.flags`` survive intact."""
    # Arrange
    src = tmp_path / "agent.yaml"
    src.write_text(
        yaml.safe_dump(
            {"metadata": {"name": "a"}, "spec": {"claude": {"flags": ["--keep-me"]}}}
        )
    )
    # Act
    got = prepare_shim_yaml(
        src,
        OrochiSpec(enabled=True, hosts=["h"]),
        write_mcp_config_file=lambda **kw: None,
    )
    # Assert
    assert yaml.safe_load(Path(got).read_text())["spec"]["claude"]["flags"] == [
        "--keep-me"
    ]


# ---------------------------------------------------------------------------
# prepare_shim_yaml — flag injection order is load-bearing
# ---------------------------------------------------------------------------


def test_prepare_shim_yaml_mcp_config_flag_precedes_dev_channels(
    tmp_path, isolated_runtime_root
):
    """``--mcp-config`` MUST precede ``--dangerously-load-development-channels``.

    From dispatch.py:78-89: the dev-channels flag references
    ``server:scitex-orochi`` which is only registered after
    ``--mcp-config`` parses the declaring JSON. Reversed order =>
    silent channel registration failure.
    """
    # Arrange
    src = tmp_path / "agent.yaml"
    src.write_text(
        yaml.safe_dump({"metadata": {"name": "agent-x"}, "spec": {"claude": {}}})
    )
    # Act
    got = prepare_shim_yaml(
        src,
        OrochiSpec(enabled=True, hosts=["h"]),
        write_mcp_config_file=lambda **kw: "/tmp/mcp-agent-x.json",
        scp_fn=FakeScp(),
    )
    flags = yaml.safe_load(Path(got).read_text())["spec"]["claude"]["flags"]
    mcp_idx = next(i for i, f in enumerate(flags) if "--mcp-config" in f)
    dev_idx = next(
        i for i, f in enumerate(flags) if "--dangerously-load-development-channels" in f
    )
    # Assert
    assert mcp_idx < dev_idx


def test_prepare_shim_yaml_dedupes_existing_flag_instances(
    tmp_path, isolated_runtime_root
):
    """Existing --mcp-config + --dangerously-... must be replaced, not duplicated."""
    # Arrange
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
    # Act
    got = prepare_shim_yaml(
        src,
        OrochiSpec(enabled=True, hosts=["h"]),
        write_mcp_config_file=lambda **kw: "/tmp/new.json",
        scp_fn=FakeScp(),
    )
    flags = yaml.safe_load(Path(got).read_text())["spec"]["claude"]["flags"]
    flag_counts = (
        sum(1 for f in flags if "--mcp-config" in f),
        sum(1 for f in flags if "--dangerously-load-development-channels" in f),
        "--keep-me" in flags,
        "/tmp/new.json" in next(f for f in flags if "--mcp-config" in f),
    )
    # Assert
    assert flag_counts == (1, 1, True, True)


def test_prepare_shim_yaml_remote_host_triggers_scp_with_documented_signature(
    tmp_path, isolated_runtime_root
):
    """``spec.remote.host`` set => ``scp_fn(local_path, host, section)``."""
    # Arrange
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
    scp = FakeScp()
    # Act
    prepare_shim_yaml(
        src,
        OrochiSpec(enabled=True, hosts=["h"]),
        write_mcp_config_file=lambda **kw: "/tmp/local-mcp.json",
        scp_fn=scp,
    )
    # Assert
    assert scp.calls == [
        (
            "/tmp/local-mcp.json",
            "spartan.example",
            {"host": "spartan.example", "user": "yw"},
        )
    ]


def test_prepare_shim_yaml_propagates_scp_failure_loudly(
    tmp_path, isolated_runtime_root
):
    """If scp raises, ``prepare_shim_yaml`` does not swallow the error."""
    # Arrange
    src = tmp_path / "agent.yaml"
    src.write_text(
        yaml.safe_dump(
            {
                "metadata": {"name": "a"},
                "spec": {"remote": {"host": "h"}, "claude": {}},
            }
        )
    )
    scp = FakeScp(raise_on_call=(1, RuntimeError("ssh boom")))
    # Act
    # Assert
    with pytest.raises(RuntimeError, match="ssh boom"):
        prepare_shim_yaml(
            src,
            OrochiSpec(enabled=True, hosts=["h"]),
            write_mcp_config_file=lambda **kw: "/tmp/local.json",
            scp_fn=scp,
        )


# ---------------------------------------------------------------------------
# _remote_home_dir — new no-fallback contract, via real ssh shim
# ---------------------------------------------------------------------------


def test_remote_home_dir_parses_last_path_line_from_chatty_bashrc(ssh_shim):
    """Chatty bashrc prepends noise; we pick the last '/'-line."""
    # Arrange
    ssh_shim.set(
        stdout="Dashboard started in background\nsome warning\n/home/yw\n", rc=0
    )
    # Act
    got = _remote_home_dir("yw@host", [])
    # Assert
    assert got == "/home/yw"


def test_remote_home_dir_raises_on_nonzero_ssh_rc(ssh_shim):
    """OLD silent-None contract is gone — non-zero rc must raise."""
    # Arrange
    ssh_shim.set(stderr="ssh: connect to host bad port 22: refused", rc=255)
    # Act
    # Assert
    with pytest.raises(RuntimeError, match="rc=255"):
        _remote_home_dir("yw@bad", [])


def test_remote_home_dir_raises_when_stdout_lacks_path_line(ssh_shim):
    """rc=0 but echo $HOME emitted no '/'-line -> raise."""
    # Arrange
    ssh_shim.set(stdout="garbled noise\n123\n", rc=0)
    # Act
    # Assert
    with pytest.raises(RuntimeError, match="no path-like line"):
        _remote_home_dir("yw@host", [])


# ---------------------------------------------------------------------------
# scp_mcp_config_to_remote — new no-fallback contract, via real ssh shim
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_file(tmp_path):
    p = tmp_path / "mcp-a.json"
    p.write_text('{"args":["/home/yw/ts/mcp_channel.ts"]}')
    return p


def test_scp_raises_when_remote_home_detect_fails(ssh_shim, mcp_file):
    """Home-detect failure (ssh rc!=0) must propagate as RuntimeError."""
    # Arrange
    ssh_shim.set(stderr="connection refused", rc=255)
    # Act
    # Assert
    with pytest.raises(RuntimeError, match="rc=255"):
        scp_mcp_config_to_remote(str(mcp_file), "h.example", {})


def test_scp_bails_after_one_ssh_call_when_home_detect_fails(ssh_shim, mcp_file):
    """On home-detect failure, no further ssh calls are attempted."""
    # Arrange
    ssh_shim.set(stderr="boom", rc=255)
    # Act
    try:
        scp_mcp_config_to_remote(str(mcp_file), "h.example", {})
    except RuntimeError:
        pass
    # Assert
    assert len(ssh_shim.calls()) == 1


def test_scp_makes_three_ssh_calls_on_homematch_success(ssh_shim, mcp_file):
    """Happy path: echo $HOME -> mkdir -p -> cat-pipe transfer = 3 calls."""
    # Arrange
    home = str(Path.home())
    mcp_file.write_text(f'{{"args":["{home}/ts/mcp_channel.ts"]}}')
    ssh_shim.set(stdout=f"{home}\n", rc=0)
    # Act
    scp_mcp_config_to_remote(str(mcp_file), "linux.example", {})
    # Assert
    assert len(ssh_shim.calls()) == 3


def test_scp_sends_raw_bytes_when_dispatcher_and_remote_home_match(ssh_shim, mcp_file):
    """Same-platform host: no rewrite, raw mcp-config bytes flow through."""
    # Arrange
    home = str(Path.home())
    mcp_file.write_text(f'{{"args":["{home}/ts/mcp_channel.ts"]}}')
    ssh_shim.set(stdout=f"{home}\n", rc=0)
    # Act
    scp_mcp_config_to_remote(str(mcp_file), "linux.example", {})
    # Assert
    assert mcp_file.read_bytes() in ssh_shim.stdins()


def test_scp_rewrites_home_prefix_to_remote_for_cross_platform(ssh_shim, mcp_file):
    """If dispatcher home != remote home, body is rewritten before transfer."""
    # Arrange
    dispatcher_home = str(Path.home())
    remote_home = "/Users/yw"  # darwin
    mcp_file.write_text(f'{{"args":["{dispatcher_home}/ts/mcp_channel.ts"]}}')
    ssh_shim.set(stdout=f"{remote_home}\n", rc=0)
    # Act
    scp_mcp_config_to_remote(str(mcp_file), "darwin.example", {})
    transfer_bodies = [s for s in ssh_shim.stdins() if s]
    body = transfer_bodies[-1].decode("utf-8")
    # Assert
    assert (remote_home in body, dispatcher_home in body) == (True, False)


def test_scp_raises_on_no_path_line_from_echo_home(ssh_shim, mcp_file):
    """rc=0 but no path-line in echo $HOME output -> RuntimeError surfaces."""
    # Arrange
    ssh_shim.set(stdout="oops bashrc noise\n", rc=0)
    # Act
    # Assert
    with pytest.raises(RuntimeError, match="no path-like line"):
        scp_mcp_config_to_remote(str(mcp_file), "h.example", {})
