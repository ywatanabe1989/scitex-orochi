"""WebSocket consumer for the browser web-terminal (todo#47).

MVP: one WS connection == one PTY. Two backends:

* ``host == "local"`` — spawns a local bash PTY on the hub container using
  ``pty.fork()``. Intended for admins who want a shell inside the hub
  container without ``docker exec``.
* any other host in :data:`TERMINAL_HOST_WHITELIST` — opens an SSH session
  via ``asyncssh`` using the hub's existing SSH identity
  (``~/.ssh/id_rsa`` or ``~/.ssh/id_ed25519``). No password prompt; if the
  hub cannot authenticate with key material the connection is closed.

Security:

* Authenticated Django users only — the consumer refuses anonymous
  scopes. Dashboard session middleware already handles this upstream.
* Destination host must appear in :data:`TERMINAL_HOST_WHITELIST`. This
  short list is maintained alongside the Machines tab registry and
  errors closed on anything else.
* No shell-escape beyond what SSH already provides: the remote user is
  whatever ``ywatanabe`` can log in as on that host with the hub's key.

Protocol (client <-> server JSON frames):

* client → ``{"type":"input","data":"ls\n"}`` — user keystrokes
* client → ``{"type":"resize","cols":120,"rows":40}`` — terminal resize
* server → ``{"type":"output","data":"..."}`` — stdout/stderr chunks
* server → ``{"type":"status","state":"connected"|"closed","msg":"..."}``
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Optional

from channels.generic.websocket import AsyncJsonWebsocketConsumer

log = logging.getLogger("orochi.terminal")

# Whitelist of target hosts the hub will open a PTY/SSH to. ``local``
# means "this container"; any other value is resolved as an SSH host
# using the hub's existing ``~/.ssh/config`` + key material. Keep this
# short — the web-terminal is a debugging surface, not a general-purpose
# tunnel gateway.
TERMINAL_HOST_WHITELIST = {
    "local",
    "mba",
    "nas",
    "spartan",
    "ywata-note-win",
    "localhost",
}

# Per-host username override. When None the hub's own whoami is used
# (falls back to ``ywatanabe`` — the canonical fleet identity).
TERMINAL_HOST_USERS = {
    "mba": "ywatanabe",
    "nas": "ywatanabe",
    "spartan": "ywatanabe",
    "ywata-note-win": "ywatanabe",
    "localhost": None,
}


class TerminalConsumer(AsyncJsonWebsocketConsumer):
    """Stream a PTY (local) or SSH session (remote) over a WebSocket."""

    async def connect(self) -> None:
        user = self.scope.get("user")
        if not (user and user.is_authenticated):
            await self.close(code=4401)
            return

        self.host: str = self.scope["url_route"]["kwargs"].get("host", "local")
        if self.host not in TERMINAL_HOST_WHITELIST:
            log.warning("terminal: rejected host=%r (not whitelisted)", self.host)
            await self.close(code=4403)
            return

        self._pid: Optional[int] = None
        self._pty_fd: Optional[int] = None
        self._ssh_conn = None  # type: ignore[assignment]
        self._ssh_proc = None  # type: ignore[assignment]
        self._reader_task: Optional[asyncio.Task] = None
        self._closed = False

        await self.accept()
        await self.send_json(
            {
                "type": "status",
                "state": "connecting",
                "msg": f"opening terminal to {self.host}...",
            }
        )

        try:
            if self.host == "local":
                await self._start_local_pty()
            else:
                await self._start_ssh_session()
        except Exception as e:  # noqa: BLE001
            log.exception("terminal: failed to open session to %s", self.host)
            await self.send_json(
                {
                    "type": "status",
                    "state": "closed",
                    "msg": f"failed: {e}",
                }
            )
            await self.close(code=4500)
            return

        await self.send_json(
            {"type": "status", "state": "connected", "msg": f"{self.host} ready"}
        )

    async def disconnect(self, code: int) -> None:
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
        # Local PTY cleanup
        if self._pty_fd is not None:
            try:
                os.close(self._pty_fd)
            except Exception:  # noqa: BLE001
                pass
            self._pty_fd = None
        if self._pid is not None:
            try:
                os.kill(self._pid, 9)
            except Exception:  # noqa: BLE001
                pass
            self._pid = None
        # SSH cleanup
        if self._ssh_proc is not None:
            try:
                self._ssh_proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            self._ssh_proc = None
        if self._ssh_conn is not None:
            try:
                self._ssh_conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._ssh_conn = None

    async def receive_json(self, content, **kwargs):  # noqa: D401
        if self._closed:
            return
        mtype = content.get("type")
        if mtype == "input":
            data = content.get("data", "")
            if not isinstance(data, str):
                return
            await self._write(data.encode("utf-8", errors="ignore"))
        elif mtype == "resize":
            cols = int(content.get("cols") or 80)
            rows = int(content.get("rows") or 24)
            await self._resize(cols, rows)
        # unknown types are silently ignored — forward compat

    # ---------------------------------------------------------------
    # Local PTY backend
    # ---------------------------------------------------------------
    async def _start_local_pty(self) -> None:
        import fcntl
        import pty
        import struct
        import termios

        shell = shutil.which("bash") or "/bin/sh"
        pid, fd = pty.fork()
        if pid == 0:
            # child — exec the shell. No return from exec on success.
            env = os.environ.copy()
            env.setdefault("TERM", "xterm-256color")
            os.execvpe(shell, [shell, "-l"], env)
            os._exit(1)  # defensive
        self._pid = pid
        self._pty_fd = fd
        # Sensible default window size; client sends resize shortly.
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        except Exception:  # noqa: BLE001
            pass
        loop = asyncio.get_running_loop()
        self._reader_task = loop.create_task(self._pty_reader_loop())

    async def _pty_reader_loop(self) -> None:
        assert self._pty_fd is not None
        loop = asyncio.get_running_loop()
        fd = self._pty_fd
        try:
            while not self._closed:
                try:
                    data = await loop.run_in_executor(None, os.read, fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                try:
                    text = data.decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    text = data.decode("latin-1", errors="replace")
                await self.send_json({"type": "output", "data": text})
        except asyncio.CancelledError:
            raise
        finally:
            if not self._closed:
                await self.send_json(
                    {"type": "status", "state": "closed", "msg": "shell exited"}
                )
                await self.close()

    # ---------------------------------------------------------------
    # SSH backend
    # ---------------------------------------------------------------
    async def _start_ssh_session(self) -> None:
        try:
            import asyncssh  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "asyncssh is not installed in the hub container — "
                "run `pip install asyncssh` and restart"
            ) from e

        username = TERMINAL_HOST_USERS.get(self.host) or os.environ.get(
            "USER", "ywatanabe"
        )
        # Rely on the hub's ~/.ssh/config + key material. known_hosts is
        # disabled for the MVP — fleet hosts may rotate keys between
        # container restarts. Tighten later when the host registry
        # exposes fingerprints.
        self._ssh_conn = await asyncssh.connect(
            self.host,
            username=username,
            known_hosts=None,
            client_keys=None,  # use ssh-agent / ~/.ssh defaults
        )
        self._ssh_proc = await self._ssh_conn.create_process(
            term_type="xterm-256color",
            term_size=(80, 24),
            encoding=None,  # binary mode — we decode on our side
        )
        loop = asyncio.get_running_loop()
        self._reader_task = loop.create_task(self._ssh_reader_loop())

    async def _ssh_reader_loop(self) -> None:
        assert self._ssh_proc is not None
        try:
            while not self._closed:
                try:
                    chunk = await self._ssh_proc.stdout.read(4096)
                except Exception:  # noqa: BLE001
                    break
                if not chunk:
                    break
                if isinstance(chunk, bytes):
                    text = chunk.decode("utf-8", errors="replace")
                else:
                    text = chunk
                await self.send_json({"type": "output", "data": text})
        except asyncio.CancelledError:
            raise
        finally:
            if not self._closed:
                await self.send_json(
                    {
                        "type": "status",
                        "state": "closed",
                        "msg": "remote session ended",
                    }
                )
                await self.close()

    # ---------------------------------------------------------------
    # Shared write/resize
    # ---------------------------------------------------------------
    async def _write(self, data: bytes) -> None:
        if self._pty_fd is not None:
            try:
                os.write(self._pty_fd, data)
            except OSError:
                pass
        elif self._ssh_proc is not None:
            try:
                self._ssh_proc.stdin.write(data)
            except Exception:  # noqa: BLE001
                pass

    async def _resize(self, cols: int, rows: int) -> None:
        cols = max(1, min(500, cols))
        rows = max(1, min(500, rows))
        if self._pty_fd is not None:
            try:
                import fcntl
                import struct
                import termios

                fcntl.ioctl(
                    self._pty_fd,
                    termios.TIOCSWINSZ,
                    struct.pack("HHHH", rows, cols, 0, 0),
                )
            except Exception:  # noqa: BLE001
                pass
        elif self._ssh_proc is not None:
            try:
                self._ssh_proc.change_terminal_size(cols, rows)
            except Exception:  # noqa: BLE001
                pass
