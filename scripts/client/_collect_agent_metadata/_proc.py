"""Process environment introspection helpers."""

from __future__ import annotations


def _read_process_env(pid: int, keys: tuple[str, ...]) -> str:
    """Return the first non-empty env value found in /proc/<pid>/environ.

    Each agent process (claude-code) carries its own env with the orochi_model
    label the runtime set at spawn — but the pusher itself runs under a
    systemd/launchd timer that has a different env. To give the dashboard
    an accurate per-agent orochi_model (not the pusher's env), peek at the
    claude process's own environ. Returns "" on any failure (no pid,
    permission denied, file gone). Never raises.

    Only works on Linux (/proc). On macOS this silently returns "" — the
    MCP sidecar's own register-path env-var chain handles the dashboard
    label there.
    """
    if not pid:
        return ""
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            raw = f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return ""
    env: dict[str, str] = {}
    for entry in raw.split(b"\x00"):
        if not entry:
            continue
        try:
            k, _, v = entry.partition(b"=")
            env[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
        except Exception:
            continue
    for k in keys:
        val = env.get(k, "").strip()
        if val:
            return val
    return ""
