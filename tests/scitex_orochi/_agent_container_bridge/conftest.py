"""Bridge-local fixtures.

Implements the two canonical no-mock patterns from the scitex-dev
``02_package/12_no-mocks.md`` skill (STX-NM001/2/3 + PA-306):

- ``env_save_restore`` — yield-based snapshot/restore of ``os.environ``
  (replaces every ``monkeypatch.setenv``).
- ``ssh_shim`` — drops a real bash script into ``tmp_path/bin/ssh`` and
  prepends it to ``$PATH``. Production code calls the real
  ``subprocess.run`` against a real (fake) ``ssh`` binary; we exercise
  the actual codepath end-to-end. Replaces every ``monkeypatch.setattr``
  on ``subprocess.run``.
- ``bash_shim`` — same idea, but for the ``bash -l -c "echo $TOK"``
  token-fallback path inside ``mcp._resolve_token``.
- ``isolated_runtime_root`` — sets ``SCITEX_DIR`` so
  ``scitex_config._ecosystem.local_state.runtime_path`` lands under a
  tmp dir, with no patching of ``local_state``.
"""

from __future__ import annotations

import os
import shlex
import stat
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# env_save_restore — replaces monkeypatch.setenv
# ---------------------------------------------------------------------------


@pytest.fixture
def env_save_restore():
    """Snapshot ``os.environ`` on entry, restore on exit.

    Yields the live ``os.environ``. Tests mutate it directly:

        def test_thing(env_save_restore):
            env_save_restore["MY_VAR"] = "x"
            ...
    """
    saved = dict(os.environ)
    try:
        yield os.environ
    finally:
        os.environ.clear()
        os.environ.update(saved)


# ---------------------------------------------------------------------------
# ssh_shim / bash_shim — real subprocess against a real fake binary
# ---------------------------------------------------------------------------


@dataclass
class _ShimController:
    """Driver for a deployed shim script.

    The shim is a real shell script that lives at ``bin_path``. Tests
    don't call it directly — production code does, via ``subprocess.run``.
    Tests:
      - read ``calls_log`` to assert how the shim was invoked.
      - mutate ``mode`` / ``stdout`` / ``stderr`` / ``rc`` to script the
        next response.
    The script re-reads its config file on every invocation.
    """

    bin_dir: Path
    bin_path: Path
    calls_log: Path
    config_path: Path
    # Mode names map to short scripts that emit canned output. Tests
    # can also supply "echo_arg" or a raw arg-script via ``set_mode``.
    mode: str = "success"
    stdout: str = ""
    stderr: str = ""
    rc: int = 0

    def write_config(self) -> None:
        """Persist current mode/stdout/stderr/rc to the config file the
        shim reads on each invocation."""
        body = (
            f"MODE={shlex.quote(self.mode)}\n"
            f"STDOUT={shlex.quote(self.stdout)}\n"
            f"STDERR={shlex.quote(self.stderr)}\n"
            f"RC={int(self.rc)}\n"
        )
        self.config_path.write_text(body)

    def calls(self) -> list[list[str]]:
        """Parsed calls log — one list-of-argv per invocation."""
        if not self.calls_log.exists():
            return []
        out: list[list[str]] = []
        for line in self.calls_log.read_text().splitlines():
            if not line:
                continue
            out.append(shlex.split(line))
        return out

    def stdins(self) -> list[bytes]:
        """Captured stdin bytes (one entry per invocation, in order)."""
        stdin_dir = self.bin_dir / "_stdins"
        if not stdin_dir.exists():
            return []
        numeric = [p for p in stdin_dir.iterdir() if p.name.isdigit()]
        return [p.read_bytes() for p in sorted(numeric, key=lambda x: int(x.name))]

    def set(
        self,
        *,
        mode: str | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        rc: int | None = None,
    ) -> None:
        """Reconfigure the shim's next response in one call."""
        if mode is not None:
            self.mode = mode
        if stdout is not None:
            self.stdout = stdout
        if stderr is not None:
            self.stderr = stderr
        if rc is not None:
            self.rc = rc
        self.write_config()


def _install_shim(bin_dir: Path, name: str) -> _ShimController:
    """Drop a real shell script at ``bin_dir/<name>`` that records argv
    + stdin, reads a config file for response, and exits with the
    configured rc."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stdin_dir = bin_dir / "_stdins"
    stdin_dir.mkdir(exist_ok=True)
    calls_log = bin_dir / f"{name}.calls"
    config_path = bin_dir / f"{name}.config"
    calls_log.write_text("")
    bin_path = bin_dir / name

    # Shebang MUST be an absolute path, not `/usr/bin/env bash`. Using
    # env would resolve `bash` via $PATH — and we just prepended the
    # shim dir to $PATH, so the kernel would loop back to interpret
    # this same fake-bash script with itself. Hard-code /bin/bash.
    script = textwrap.dedent(
        f"""\
        #!/bin/bash
        set -eu
        # Record argv (one shell-quoted line per invocation).
        printf '%q ' "$@" >> {shlex.quote(str(calls_log))}
        printf '\\n'   >> {shlex.quote(str(calls_log))}
        # Persist stdin bytes for later inspection.
        STDIN_IDX_FILE={shlex.quote(str(stdin_dir / "_idx"))}
        if [ -f "$STDIN_IDX_FILE" ]; then
            IDX=$(cat "$STDIN_IDX_FILE")
        else
            IDX=0
        fi
        cat > {shlex.quote(str(stdin_dir))}/$IDX
        echo $((IDX + 1)) > "$STDIN_IDX_FILE"
        # Read response from config (defaults if missing).
        MODE=success
        STDOUT=
        STDERR=
        RC=0
        if [ -f {shlex.quote(str(config_path))} ]; then
            # shellcheck disable=SC1090
            . {shlex.quote(str(config_path))}
        fi
        case "$MODE" in
            success)
                printf '%s' "$STDOUT"
                printf '%s' "$STDERR" >&2
                exit "$RC"
                ;;
            *)
                printf '%s' "$STDERR" >&2
                exit "$RC"
                ;;
        esac
        """
    )
    bin_path.write_text(script)
    bin_path.chmod(bin_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    ctrl = _ShimController(
        bin_dir=bin_dir,
        bin_path=bin_path,
        calls_log=calls_log,
        config_path=config_path,
    )
    ctrl.write_config()
    return ctrl


@pytest.fixture
def ssh_shim(tmp_path, env_save_restore):
    """Install a real fake ``ssh`` binary on ``$PATH`` (highest precedence).

    Returns a ``_ShimController`` for the deployed script. Production
    ``subprocess.run(["ssh", ...])`` calls the fake; tests assert via
    ``ctrl.calls()`` and ``ctrl.stdins()``.

    Default behaviour is rc=0, no stdout, no stderr. Call
    ``ctrl.set(stdout=..., rc=..., stderr=...)`` to script the next
    invocation.
    """
    bin_dir = tmp_path / "shim_bin_ssh"
    ctrl = _install_shim(bin_dir, "ssh")
    env_save_restore["PATH"] = (
        f"{bin_dir}{os.pathsep}{env_save_restore.get('PATH', '')}"
    )
    return ctrl


@pytest.fixture
def bash_shim(tmp_path, env_save_restore):
    """Install a real fake ``bash`` binary on ``$PATH`` (highest precedence).

    Used to exercise ``mcp._resolve_token``'s ``bash -l -c "echo $TOK"``
    fallback without touching the real login shell.

    NB: scoping this is risky — production code runs many bash
    subprocesses. We accept the blast radius for these tests because
    the only path under test that shells out to bash is the token
    fallback, and tests are short-lived per-function fixtures.
    """
    bin_dir = tmp_path / "shim_bin_bash"
    ctrl = _install_shim(bin_dir, "bash")
    env_save_restore["PATH"] = (
        f"{bin_dir}{os.pathsep}{env_save_restore.get('PATH', '')}"
    )
    return ctrl


# ---------------------------------------------------------------------------
# isolated_runtime_root — replaces monkeypatch of local_state.runtime_path
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_runtime_root(tmp_path, env_save_restore) -> Path:
    """Point ``scitex_config._ecosystem.local_state.runtime_path`` at a tmp dir.

    ``local_state.user_root()`` reads ``SCITEX_DIR`` (default
    ``~/.scitex``) on every call. ``local_state.find_project_scope()``
    walks up from cwd looking for ``.git``. We:
      - set ``SCITEX_DIR=tmp_path/scitex``
      - change cwd to a tmp dir with no ``.git``
    so all ``runtime_path`` lookups land under ``tmp_path``.
    """
    scitex_root = tmp_path / "scitex"
    cwd_root = tmp_path / "cwd"
    cwd_root.mkdir()
    env_save_restore["SCITEX_DIR"] = str(scitex_root)
    saved_cwd = Path.cwd()
    os.chdir(cwd_root)
    try:
        yield scitex_root
    finally:
        os.chdir(saved_cwd)


# ---------------------------------------------------------------------------
# Hand-rolled fake for scp_fn DI in prepare_shim_yaml
# ---------------------------------------------------------------------------


@dataclass
class FakeScp:
    """Honest fake for ``scp_mcp_config_to_remote`` — records its calls.

    Used via the ``scp_fn`` kwarg on ``prepare_shim_yaml``. Production
    callers omit ``scp_fn`` (it resolves to the real function). Tests
    pass a fresh ``FakeScp()`` and inspect ``.calls`` after the SUT runs.

    The fake exposes only the call signature production uses
    (``(local_path: str, remote_host: str, remote_section: dict)``)
    plus a ``calls`` list — no extra "magic" attributes. If production
    grows another arg or the signature shifts, this fake's
    ``__call__`` will be wrong and the test will fail loudly, which is
    the property we want.
    """

    calls: list[tuple[str, str, dict]] = field(default_factory=list)
    # If non-None, raised on the n-th call (one-indexed).
    raise_on_call: tuple[int, BaseException] | None = None

    def __call__(self, local_path: str, remote_host: str, remote_section: dict) -> None:
        self.calls.append((local_path, remote_host, dict(remote_section)))
        if self.raise_on_call is not None and len(self.calls) == self.raise_on_call[0]:
            raise self.raise_on_call[1]
