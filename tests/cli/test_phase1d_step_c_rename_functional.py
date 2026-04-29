"""Functional tests for the noun-verb CLI surface (Phase 1d Step C, plan PR #337 §2).

After the grace period for legacy verb-noun aliases expired (msg#17078
follow-up), the rename shims were deleted entirely:

* the canonical noun-verb form must work (``scitex-orochi agent launch``);
* the legacy flat form is gone — invoking it produces Click's standard
  ``Error: No such command '<old>'.`` and exits non-zero. There is no
  forward-pointer redirect; the §5 grace contract has ended for these
  commands.

We assert the canonical form for every renamed verb (parametrized) and
keep one representative legacy-name regression check so a future
accidental re-addition of a shim is caught.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi

# Canonical noun-verb paths that replaced the deleted flat aliases.
NEW_PATHS: list[list[str]] = [
    ["agent", "launch"],
    ["agent", "restart"],
    ["agent", "status"],
    ["agent", "stop"],
    ["agent", "list"],
    ["agent", "fleet-list"],
    ["message", "send"],
    ["message", "listen"],
    ["channel", "history"],
    ["channel", "join"],
    ["channel", "list"],
    ["channel", "members"],
    ["invite", "create"],
    ["invite", "list"],
    ["workspace", "create"],
    ["workspace", "delete"],
    ["workspace", "list"],
    ["server", "status"],
    ["server", "start"],
    ["server", "deploy"],
    ["push", "setup"],
    ["config", "init"],
    ["system", "doctor"],
    ["auth", "login"],
    ["machine", "heartbeat", "send"],
    ["hook", "report"],
]


@pytest.mark.parametrize("new_path", NEW_PATHS)
def test_new_form_help_is_reachable(new_path: list[str]) -> None:
    """The migrated verb is reachable via the nested noun-verb path."""
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        new_path + ["--help"],
        obj={"host": "127.0.0.1", "port": 9559},
    )
    assert result.exit_code == 0, (
        f"`scitex-orochi {' '.join(new_path)} --help` failed.\n"
        f"exit: {result.exit_code}\noutput: {result.output}\n"
        f"exception: {result.exception!r}"
    )
    # Click puts "Usage:" at the top of every help invocation.
    assert "Usage:" in result.output


def test_legacy_flat_alias_hard_errors_with_rename_message() -> None:
    """Representative regression check: the former flat alias
    ``agent-launch`` is registered as a hidden stub that emits the
    canonical rename error and exits 2. Hidden != removed (PR #347).
    """
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["agent-launch"], obj={"host": "127.0.0.1", "port": 9559}
    )
    assert result.exit_code == 2, (
        f"expected exit 2 from hidden rename stub; got {result.exit_code}\n"
        f"output: {result.output}"
    )
    assert (
        "error: `scitex-orochi agent-launch` was renamed to `scitex-orochi agent launch`."
    ) in result.output, (
        f"expected canonical rename error message; got:\n{result.output}"
    )
