"""Tests for ``_agent_container_bridge/mcp.py``.

Compliant with scitex-dev linter:
- STX-NM001/2/3: no mock/monkeypatch/patch/Mock anywhere.
- STX-TQ002: every test carries Arrange/Act/Assert markers.
- STX-TQ007: every test asserts exactly one claim.

Real-collaborator strategy (per ``02_package/12_no-mocks.md``):

- env vars: ``env_save_restore`` fixture (yield-based snapshot/restore).
- ``mcp_channel.ts`` resolution: write a real file into ``tmp_path``
  and steer ``find_mcp_channel_ts`` to it via the env-var branch.
- ``bash -l`` token fallback: ``bash_shim`` drops a real fake ``bash``
  binary on ``$PATH``; production ``subprocess.run`` invokes it.
- ``local_state.runtime_path``: ``isolated_runtime_root`` sets
  ``SCITEX_DIR`` + cd's out of any git repo, with no patching of
  ``local_state``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitex_orochi._agent_container_bridge.mcp import (
    _resolve_token,
    build_orochi_mcp_config,
    find_mcp_channel_ts,
    write_mcp_config_file,
)
from scitex_orochi._agent_container_bridge.spec import OrochiSpec

# A token_env name that nothing in any shell init file exports — keeps
# ``_resolve_token`` deterministic across dev boxes when we don't set
# the env var ourselves.
_UNSET_TOKEN_ENV = "SCITEX_ORO_BRIDGE_TEST_UNSET_TOKEN_98765"


# ---------------------------------------------------------------------------
# find_mcp_channel_ts — 4-level fallback chain
# ---------------------------------------------------------------------------


def test_find_ts_explicit_path_wins(tmp_path, env_save_restore):
    """An explicit existing ts_path short-circuits everything below."""
    # Arrange
    explicit = tmp_path / "explicit.ts"
    explicit.write_text("// fake")
    other = tmp_path / "env.ts"
    other.write_text("// fake")
    env_save_restore["SCITEX_OROCHI_PUSH_TS"] = str(other)
    # Act
    got = find_mcp_channel_ts(str(explicit))
    # Assert
    assert got == str(explicit)


def test_find_ts_explicit_missing_falls_through_to_env(tmp_path, env_save_restore):
    """A non-existent explicit path is silently skipped — env wins."""
    # Arrange
    explicit = tmp_path / "does-not-exist.ts"
    env_ts = tmp_path / "env.ts"
    env_ts.write_text("// fake")
    env_save_restore["SCITEX_OROCHI_PUSH_TS"] = str(env_ts)
    # Act
    got = find_mcp_channel_ts(str(explicit))
    # Assert
    assert got == str(env_ts)


def test_find_ts_env_path_is_picked_up(tmp_path, env_save_restore):
    """No explicit -> ``SCITEX_OROCHI_PUSH_TS`` is consulted."""
    # Arrange
    env_ts = tmp_path / "env.ts"
    env_ts.write_text("// fake")
    env_save_restore["SCITEX_OROCHI_PUSH_TS"] = str(env_ts)
    # Act
    got = find_mcp_channel_ts("")
    # Assert
    assert got == str(env_ts)


def test_find_ts_never_returns_a_nonexistent_path(env_save_restore):
    """Invariant: the resolved path must exist on disk (or be None).

    The package-relative + ``/opt`` fallback branches are environment-
    dependent; we only assert the function's structural contract:
    either return a real file, or return ``None`` — never a broken path.
    """
    # Arrange
    env_save_restore.pop("SCITEX_OROCHI_PUSH_TS", None)
    # Act
    got = find_mcp_channel_ts("")
    # Assert
    assert got is None or Path(got).is_file()


# ---------------------------------------------------------------------------
# _resolve_token — 3-level fallback chain
# ---------------------------------------------------------------------------


def test_resolve_token_from_agent_env_wins(env_save_restore):
    """Per-agent token in spec.env takes precedence over os.environ."""
    # Arrange
    env_save_restore["SCITEX_OROCHI_TOKEN"] = "from-os-env"
    spec = OrochiSpec(token_env="SCITEX_OROCHI_TOKEN")
    agent_env = {"SCITEX_OROCHI_TOKEN": "from-agent-env"}
    # Act
    got = _resolve_token(spec, agent_env)
    # Assert
    assert got == "from-agent-env"


def test_resolve_token_from_os_environ(env_save_restore):
    """When agent_env lacks the key, os.environ is the next fallback."""
    # Arrange
    env_save_restore["SCITEX_OROCHI_TOKEN"] = "from-os-env"
    spec = OrochiSpec(token_env="SCITEX_OROCHI_TOKEN")
    # Act
    got = _resolve_token(spec, {})
    # Assert
    assert got == "from-os-env"


def test_resolve_token_bash_fallback_returns_canned_token(env_save_restore, bash_shim):
    """When neither dict has the token, prod shells out to bash -l."""
    # Arrange
    env_save_restore.pop("SCITEX_OROCHI_TOKEN", None)
    bash_shim.set(stdout="bash-fallback-token\n", rc=0)
    spec = OrochiSpec(token_env="SCITEX_OROCHI_TOKEN")
    # Act
    got = _resolve_token(spec, {})
    # Assert
    assert got == "bash-fallback-token"


def test_resolve_token_bash_fallback_uses_login_shell_with_echo(
    env_save_restore, bash_shim
):
    """The bash fallback invokes ``bash -l -c "echo $TOK"`` — assert argv."""
    # Arrange
    env_save_restore.pop("SCITEX_OROCHI_TOKEN", None)
    bash_shim.set(stdout="x\n", rc=0)
    spec = OrochiSpec(token_env="SCITEX_OROCHI_TOKEN")
    # Act
    _resolve_token(spec, {})
    # Assert
    assert bash_shim.calls() == [["-l", "-c", "echo $SCITEX_OROCHI_TOKEN"]]


def test_resolve_token_bash_fallback_empty_stdout_returns_empty(
    env_save_restore, bash_shim
):
    """Empty bash output isn't a failure — caller treats "" as "no token"."""
    # Arrange
    env_save_restore.pop("SCITEX_OROCHI_TOKEN", None)
    bash_shim.set(stdout="\n", rc=0)
    # Act
    got = _resolve_token(OrochiSpec(), {})
    # Assert
    assert got == ""


def test_resolve_token_bash_fallback_nonzero_rc_returns_empty(
    env_save_restore, bash_shim
):
    """Non-zero rc from bash is swallowed by design — no token, no crash."""
    # Arrange
    env_save_restore.pop("SCITEX_OROCHI_TOKEN", None)
    bash_shim.set(stdout="", stderr="login failed", rc=2)
    # Act
    got = _resolve_token(OrochiSpec(), {})
    # Assert
    assert got == ""


# ---------------------------------------------------------------------------
# build_orochi_mcp_config — short-circuit paths
# ---------------------------------------------------------------------------


def test_build_returns_none_when_orochi_disabled():
    """``OrochiSpec()`` with enabled=False short-circuits to None."""
    # Arrange
    spec = OrochiSpec()
    # Act
    got = build_orochi_mcp_config(
        agent_name="a", orochi=spec, agent_env={}, agent_labels={}
    )
    # Assert
    assert got is None


def test_build_returns_real_file_path_or_none(env_save_restore, tmp_path):
    """Enabled + unresolvable explicit ts: result is either None
    (genuinely no ts on this box) or a path that is a real file.

    Pins the public invariant — no broken paths emitted.
    """
    # Arrange
    env_save_restore.pop("SCITEX_OROCHI_PUSH_TS", None)
    spec = OrochiSpec(enabled=True, hosts=["h"], ts_path=str(tmp_path / "nope.ts"))
    # Act
    got = build_orochi_mcp_config(
        agent_name="a", orochi=spec, agent_env={}, agent_labels={}
    )
    # Assert
    assert got is None or Path(got["mcpServers"]["scitex-orochi"]["args"][0]).is_file()


# ---------------------------------------------------------------------------
# build_orochi_mcp_config — happy-path JSON shape
# ---------------------------------------------------------------------------


def test_build_full_config_shape_when_enabled(tmp_path, env_save_restore):
    """Happy path — the assembled config matches the documented shape.

    Single dict-equality assertion bundles all happy-path fields.
    """
    # Arrange
    ts = tmp_path / "mcp_channel.ts"
    ts.write_text("// fake")
    env_save_restore["SCITEX_OROCHI_PUSH_TS"] = str(ts)
    env_save_restore.pop("SCITEX_OROCHI_TOKEN", None)
    spec = OrochiSpec(
        enabled=True,
        hosts=["primary.example", "secondary.example"],
        port=8559,
        token_env=_UNSET_TOKEN_ENV,
    )
    expected = {
        "mcpServers": {
            "scitex-orochi": {
                "type": "stdio",
                "command": "bun",
                "args": [str(ts)],
                "env": {
                    "SCITEX_OROCHI_HOST": "primary.example",
                    "SCITEX_OROCHI_PORT": "8559",
                    "SCITEX_OROCHI_AGENT": "proj-agent-x",
                    "SCITEX_OROCHI_TELEGRAM_BOT_TOKEN": "",
                    "SCITEX_OROCHI_AGENT_ROLE": "",
                },
            }
        }
    }
    # Act
    got = build_orochi_mcp_config(
        agent_name="proj-agent-x",
        orochi=spec,
        agent_env={},
        agent_labels={},
    )
    # Assert
    assert got == expected


def test_build_injects_token_when_resolvable(tmp_path, env_save_restore):
    """When a token is resolvable, it lands in the env block."""
    # Arrange
    ts = tmp_path / "ts"
    ts.write_text("// fake")
    env_save_restore["SCITEX_OROCHI_PUSH_TS"] = str(ts)
    spec = OrochiSpec(enabled=True, hosts=["h"], token_env="MY_TOK")
    # Act
    got = build_orochi_mcp_config(
        agent_name="a",
        orochi=spec,
        agent_env={"MY_TOK": "shhh"},
        agent_labels={},
    )
    # Assert
    assert got["mcpServers"]["scitex-orochi"]["env"]["SCITEX_OROCHI_TOKEN"] == "shhh"


@pytest.mark.parametrize(
    "labels, expected_triple",
    [
        # (labels, (icon_env, icon_emoji_env, icon_text_env))
        # SCITEX_OROCHI_ICON chain (mcp.py:157-161) = icon-image OR
        # icon-emoji OR labels['icon'] OR env['SCITEX_OROCHI_ICON'].
        # icon-text does NOT feed SCITEX_OROCHI_ICON.
        ({"icon-image": "img.png"}, ("img.png", None, None)),
        ({"icon-emoji": "P"}, ("P", "P", None)),
        ({"icon-text": "AG"}, (None, None, "AG")),
        (
            {"icon-image": "img.png", "icon-emoji": "P", "icon-text": "AG"},
            ("img.png", "P", "AG"),
        ),
        ({}, (None, None, None)),
    ],
)
def test_build_icon_env_block_matches_label_chain(
    tmp_path, env_save_restore, labels, expected_triple
):
    """icon env triple is (ICON, ICON_EMOJI, ICON_TEXT) per the chain."""
    # Arrange
    ts = tmp_path / "ts"
    ts.write_text("// fake")
    env_save_restore["SCITEX_OROCHI_PUSH_TS"] = str(ts)
    env_save_restore.pop("SCITEX_OROCHI_ICON", None)
    spec = OrochiSpec(enabled=True, hosts=["h"], token_env=_UNSET_TOKEN_ENV)
    # Act
    env = build_orochi_mcp_config(
        agent_name="a", orochi=spec, agent_env={}, agent_labels=labels
    )["mcpServers"]["scitex-orochi"]["env"]
    actual_triple = (
        env.get("SCITEX_OROCHI_ICON"),
        env.get("SCITEX_OROCHI_ICON_EMOJI"),
        env.get("SCITEX_OROCHI_ICON_TEXT"),
    )
    # Assert
    assert actual_triple == expected_triple


# ---------------------------------------------------------------------------
# write_mcp_config_file — disk side-effect
# ---------------------------------------------------------------------------


def test_write_returns_none_when_orochi_disabled():
    """Short-circuits to None when Orochi isn't enabled."""
    # Arrange
    spec = OrochiSpec()
    # Act
    got = write_mcp_config_file(
        agent_name="a", orochi=spec, agent_env={}, agent_labels={}
    )
    # Assert
    assert got is None


def test_write_returns_path_under_runtime_root_with_agent_name_filename(
    tmp_path, env_save_restore, isolated_runtime_root
):
    """The written file lives under SCITEX_DIR/orochi/runtime and is
    named ``mcp-<agent>.json`` per the documented layout."""
    # Arrange
    ts = tmp_path / "ts"
    ts.write_text("// fake")
    env_save_restore["SCITEX_OROCHI_PUSH_TS"] = str(ts)
    spec = OrochiSpec(enabled=True, hosts=["h"])
    # Act
    got = write_mcp_config_file(
        agent_name="proj-agent-y",
        orochi=spec,
        agent_env={},
        agent_labels={},
    )
    out = Path(got)
    actual = (
        str(out).startswith(str(isolated_runtime_root)),
        out.name,
    )
    # Assert
    assert actual == (True, "mcp-proj-agent-y.json")


def test_write_creates_file_whose_json_carries_the_agent_name(
    tmp_path, env_save_restore, isolated_runtime_root
):
    """The on-disk JSON body has the agent name in the env block."""
    # Arrange
    ts = tmp_path / "ts"
    ts.write_text("// fake")
    env_save_restore["SCITEX_OROCHI_PUSH_TS"] = str(ts)
    spec = OrochiSpec(enabled=True, hosts=["h"])
    # Act
    out = Path(
        write_mcp_config_file(
            agent_name="proj-agent-y",
            orochi=spec,
            agent_env={},
            agent_labels={},
        )
    )
    written = json.loads(out.read_text())
    # Assert
    assert (
        written["mcpServers"]["scitex-orochi"]["env"]["SCITEX_OROCHI_AGENT"]
        == "proj-agent-y"
    )
