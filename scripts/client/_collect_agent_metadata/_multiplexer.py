"""tmux/screen orochi_multiplexer detection and enumeration."""

from __future__ import annotations

import re
import subprocess


def detect_multiplexer(agent: str) -> str:
    """Return 'tmux', 'screen', or '' if not found."""
    if (
        subprocess.run(
            ["tmux", "has-session", "-t", agent],
            capture_output=True,
        ).returncode
        == 0
    ):
        return "tmux"
    r = subprocess.run(
        ["screen", "-ls", agent],
        capture_output=True,
        text=True,
    )
    if agent in r.stdout:
        return "screen"
    return ""


def _list_local_agents() -> list[str]:
    """Enumerate tmux + screen sessions present on this host."""
    names: list[str] = []
    try:
        out = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        if out.returncode == 0:
            names.extend(n.strip() for n in out.stdout.splitlines() if n.strip())
    except FileNotFoundError:
        pass
    try:
        out = subprocess.run(
            ["screen", "-ls"],
            capture_output=True,
            text=True,
        )
        for line in out.stdout.splitlines():
            m = re.match(r"\s*\d+\.(\S+)\s", line)
            if m:
                names.append(m.group(1))
    except FileNotFoundError:
        pass
    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq = []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq
