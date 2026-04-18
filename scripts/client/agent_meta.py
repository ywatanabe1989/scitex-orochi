#!/usr/bin/env -S python3 -u
from __future__ import annotations

"""Extract claude-hud-like metadata for an Orochi agent.

DEPRECATED 2026-04-12: superseded by ``scitex-agent-container status
<name> --json``, which is now the canonical source of truth for this
metadata payload (see scitex-agent-container commit 204efa6 and
scitex-orochi commit 351540f — the MCP sidecar heartbeat has been
refactored to shell out to the CLI instead of reimplementing collection
in TypeScript).

This module is kept temporarily for mamba-healer-mba's standalone
``--push`` mode until the sidecar heartbeat is fully verified across all
hosts (head-mba, head-ywata-note-win, head-nas, head-spartan). New
callers should use ``scitex-agent-container status`` directly.

Usage:
    agent_meta.py <agent_name>
        Print JSON metadata for one agent to stdout (legacy behavior).

    agent_meta.py --push [--url URL] [--token TOKEN]
        Enumerate all local tmux/screen agent sessions, collect metadata
        for each, and POST each entry to the Orochi hub's
        /api/agents/register/ heartbeat endpoint so the Agents dashboard
        shows multiplexer, pid, context_pct, model, current task,
        subagent count, skills, started_at etc.

        URL defaults to $SCITEX_OROCHI_URL_HTTP, else https://scitex-orochi.com
        TOKEN defaults to $SCITEX_OROCHI_TOKEN (workspace token).

        Skipped entirely if $SCITEX_OROCHI_REGISTRY_DISABLE=1.

Outputs JSON: {agent, alive, subagents, context_pct, current_tool,
last_activity, model, multiplexer}
"""
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("agent_meta")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s agent_meta %(message)s",
    )


def _resolve_canonical_hostname() -> str:
    """Best-effort canonical hostname for dashboard display (todo#55).

    On Linux ``socket.getfqdn()`` usually returns a sensible
    ``host.example.com``. On macOS (and some containers) it can return the
    IPv6 loopback PTR — e.g. ``1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0
    .0.0.0.0.0.0.0.0.0.0.ip6.arpa`` — which is worse than useless. In that
    case we prefer ``socket.gethostname()`` which returns the user-meaningful
    ``*.local`` / ``*.localdomain`` name the user recognises.
    """
    try:
        fqdn = (socket.getfqdn() or "").strip()
    except Exception:
        fqdn = ""
    try:
        short = (socket.gethostname() or "").strip()
    except Exception:
        short = ""
    looks_bogus = (
        not fqdn
        or fqdn.endswith(".arpa")
        or fqdn == "localhost"
        or fqdn == "localhost.localdomain"
    )
    if looks_bogus:
        return short
    return fqdn


def read_oauth_metadata(claude_json_path=None) -> dict:
    """Return Claude Code OAuth account public metadata (todo#265).

    Reads ``~/.claude.json`` and extracts a strict whitelist of 9
    non-sensitive fields so the Orochi hub's Agents/Activity tab can
    show which account each agent is running under, detect
    out_of_credits state, and support fleet load-balancing.

    SECURITY: This function is whitelist-only. It NEVER reads
    ``~/.claude/.credentials.json`` and NEVER emits any field whose
    name contains ``token``, ``secret``, or ``key``. The final assert
    is a belt-and-braces regression guard against future edits.

    Returns {} on any read/parse error so --push degrades gracefully.
    """
    path = claude_json_path or (Path.home() / ".claude.json")
    try:
        if not path.is_file():
            return {}
        doc = json.loads(path.read_text())
    except Exception as e:
        log.warning("read_oauth_metadata: %s", e)
        return {}
    if not isinstance(doc, dict):
        return {}
    oauth = doc.get("oauthAccount") or {}
    if not isinstance(oauth, dict):
        oauth = {}
    result: dict = {
        "oauth_email": oauth.get("emailAddress") or "",
        "oauth_org_name": oauth.get("organizationName") or "",
        "oauth_account_uuid": oauth.get("accountUuid") or "",
        "oauth_display_name": oauth.get("displayName") or "",
        "billing_type": oauth.get("billingType") or "",
        "has_available_subscription": doc.get("hasAvailableSubscription"),
        "usage_disabled_reason": doc.get("cachedExtraUsageDisabledReason") or "",
        "has_extra_usage_enabled": oauth.get("hasExtraUsageEnabled"),
        "subscription_created_at": oauth.get("subscriptionCreatedAt") or "",
    }
    # Token-leak regression guard (todo#265). If any future edit adds
    # a key containing token/secret/key, this assertion fires BEFORE
    # the data hits the wire.
    assert all(
        "token" not in k.lower()
        and "secret" not in k.lower()
        and "key" not in k.lower()
        for k in result
    ), "read_oauth_metadata: forbidden key in whitelist"
    return result


_HOOK_EVENT_KEYS = (
    "recent_tools",
    "recent_prompts",
    "tool_counts",
    "last_tool_name",
    "last_tool_at",
    "last_mcp_tool_name",
    "last_mcp_tool_at",
    "last_action_name",
    "last_action_at",
    "last_action_outcome",
    "last_action_elapsed_s",
    "p95_elapsed_s_by_action",
)


def _collect_hook_events(agent: str) -> dict:
    """Read hook-event ring-buffer summary via scitex-agent-container.

    scitex-orochi todo#187 / #59: the per-agent Last tool / Last MCP /
    Last action rows stay empty because this heartbeat script never
    pulled these fields from the hook-event ring buffer. Shell-out is
    short-lived (<1 s) and bounded by ``timeout``; on any failure we
    return an empty dict so the rest of the heartbeat still flows.
    """
    try:
        proc = subprocess.run(
            ["scitex-agent-container", "status", agent, "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return {}
        data = json.loads(proc.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return {}
    return {k: data[k] for k in _HOOK_EVENT_KEYS if k in data}


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


def main(agent: str) -> None:
    """CLI entry point — print rich JSON for one agent.

    Refactored 2026-04-13 to call collect() so the legacy CLI path and
    the --push heartbeat path share a single source of truth, including
    the SKIP_TOOLS filter and tool input preview that hide the noisy
    mcp__scitex-orochi__* housekeeping calls (todo#155 / msg#6546).
    """
    print(json.dumps(collect(agent)))


def collect_machine_metrics() -> dict:
    """Cross-OS host resource snapshot for the Orochi Machines tab (todo#329).

    Reads CPU/memory/disk/load via psutil if available; falls back to a
    minimal stdlib best-effort if psutil is missing. Output keys match
    what ``hub/views/api.py:api_resources`` projects into the per-machine
    Machines tab card. Empty/None on any read error so the receiver
    degrades gracefully.
    """
    out: dict[str, Any] = {
        "cpu_count": None,
        "cpu_model": "",
        "load_avg_1m": None,
        "load_avg_5m": None,
        "load_avg_15m": None,
        "mem_used_percent": None,
        "mem_total_mb": None,
        "mem_free_mb": None,
        "disk_used_percent": None,
    }
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None  # type: ignore

    try:
        if psutil is not None:
            out["cpu_count"] = psutil.cpu_count(logical=True)
        else:
            out["cpu_count"] = os.cpu_count()
    except Exception:
        pass

    try:
        if hasattr(os, "getloadavg"):
            l1, l5, l15 = os.getloadavg()
            out["load_avg_1m"] = round(l1, 2)
            out["load_avg_5m"] = round(l5, 2)
            out["load_avg_15m"] = round(l15, 2)
    except Exception:
        pass

    # Memory: try psutil first, then stdlib /proc/meminfo (Linux), then
    # /usr/sbin/sysctl + vm_stat (Darwin). psutil is not always installed
    # in the python3 PATH the heartbeat shell-out picks (the bun MCP
    # sidecar inherits whatever PATH is active in the agent's tmux pane —
    # if that's a non-venv shell, psutil import fails and we'd lose all
    # mem fields without this fallback).
    try:
        if psutil is not None:
            vm = psutil.virtual_memory()
            out["mem_total_mb"] = int(vm.total / 1024 / 1024)
            out["mem_free_mb"] = int(
                vm.available / 1024 / 1024
            )  # use "available", not "free" — Darwin/Linux semantics (todo#310)
            out["mem_used_percent"] = round(
                (vm.total - vm.available) * 100.0 / max(vm.total, 1), 1
            )
        else:
            raise ImportError
    except Exception:
        try:
            if sys.platform.startswith("linux"):
                with open("/proc/meminfo") as f:
                    kv: dict[str, int] = {}
                    for ln in f:
                        m = re.match(r"(\w+):\s+(\d+)\s*kB", ln)
                        if m:
                            kv[m.group(1)] = int(m.group(2)) * 1024
                total = kv.get("MemTotal")
                avail = kv.get("MemAvailable", kv.get("MemFree"))
                if total and avail is not None:
                    out["mem_total_mb"] = int(total / 1024 / 1024)
                    out["mem_free_mb"] = int(avail / 1024 / 1024)
                    out["mem_used_percent"] = round(
                        (total - avail) * 100.0 / max(total, 1), 1
                    )
            elif sys.platform == "darwin":
                import subprocess as _sp

                total_bytes = int(
                    _sp.check_output(
                        ["/usr/sbin/sysctl", "-n", "hw.memsize"], text=True
                    ).strip()
                )
                vm_out = _sp.check_output(["vm_stat"], text=True)
                page_size = 4096
                mp = re.search(r"page size of (\d+) bytes", vm_out)
                if mp:
                    page_size = int(mp.group(1))
                pages: dict[str, int] = {}
                for ln in vm_out.splitlines():
                    mm = re.match(r"(.+?):\s+(\d+)", ln)
                    if mm:
                        pages[mm.group(1).strip()] = int(mm.group(2))
                # Darwin: free + inactive + speculative (todo#310)
                free_bytes = (
                    pages.get("Pages free", 0)
                    + pages.get("Pages inactive", 0)
                    + pages.get("Pages speculative", 0)
                ) * page_size
                out["mem_total_mb"] = int(total_bytes / 1024 / 1024)
                out["mem_free_mb"] = int(free_bytes / 1024 / 1024)
                out["mem_used_percent"] = round(
                    (total_bytes - free_bytes) * 100.0 / max(total_bytes, 1), 1
                )
        except Exception:
            pass

    # Disk: try psutil, then statvfs
    try:
        if psutil is not None:
            du = psutil.disk_usage(os.path.expanduser("~"))
            out["disk_used_percent"] = round(du.percent, 1)
        else:
            raise ImportError
    except Exception:
        try:
            st = os.statvfs(os.path.expanduser("~"))
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            if total > 0:
                out["disk_used_percent"] = round((total - free) * 100.0 / total, 1)
        except Exception:
            pass

    try:
        # cpu_model — best-effort, OS-specific
        import platform

        out["cpu_model"] = platform.processor() or ""
    except Exception:
        pass

    return out


def collect_slurm_status():
    """Snapshot of SLURM compute resources for HPC hosts (todo#59).

    Returns ``None`` on hosts where SLURM is not installed (most fleet
    nodes), so the receiver can hide the SLURM card cleanly. On hosts
    where ``squeue`` and ``sinfo`` exist, returns a compact dict that
    the dashboard can render without further parsing::

        {
          "running_jobs":     int,         # squeue -t R for current user
          "pending_jobs":     int,         # squeue -t PD for current user
          "running_job_ids":  [str, ...],  # up to 5 most recent
          "running_partitions": [str, ...],
          "running_nodes":      [str, ...],
          "partitions":       {            # sinfo summary, top 4 partitions
              "<name>": {"idle": int, "alloc": int, "down": int, "total": int},
              ...
          },
          "user":             str,
        }

    All fields are best-effort; per-source try/except so that a stray
    line in ``squeue`` output never breaks the heartbeat. The whole
    snapshot is bounded — never more than ~5 jobs and 4 partitions —
    so it cannot bloat the WS message.
    """
    if shutil.which("squeue") is None:
        return None

    out: dict[str, Any] = {
        "running_jobs": 0,
        "pending_jobs": 0,
        "running_job_ids": [],
        "running_partitions": [],
        "running_nodes": [],
        "partitions": {},
        "user": os.environ.get("USER", ""),
    }

    user = out["user"]
    try:
        proc = subprocess.run(
            [
                "squeue",
                "-u",
                user,
                "-h",
                "-o",
                "%i|%P|%T|%R",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if proc.returncode == 0:
            running_ids: list[str] = []
            running_parts: list[str] = []
            running_nodes: list[str] = []
            r_count = 0
            p_count = 0
            for raw in proc.stdout.splitlines():
                parts = raw.strip().split("|")
                if len(parts) < 4:
                    continue
                jid, part, state, nodelist = parts[:4]
                if state == "RUNNING":
                    r_count += 1
                    if len(running_ids) < 5:
                        running_ids.append(jid)
                        running_parts.append(part)
                        running_nodes.append(nodelist)
                elif state == "PENDING":
                    p_count += 1
            out["running_jobs"] = r_count
            out["pending_jobs"] = p_count
            out["running_job_ids"] = running_ids
            out["running_partitions"] = running_parts
            out["running_nodes"] = running_nodes
    except Exception:
        pass

    if shutil.which("sinfo") is not None:
        try:
            proc = subprocess.run(
                [
                    "sinfo",
                    "-h",
                    "-o",
                    "%P %T %D",
                ],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if proc.returncode == 0:
                table: dict[str, dict[str, int]] = {}
                for raw in proc.stdout.splitlines():
                    fields = raw.split()
                    if len(fields) < 3:
                        continue
                    part_name, state, count_str = fields[0], fields[1], fields[2]
                    part_name = part_name.rstrip("*")
                    try:
                        count = int(count_str)
                    except ValueError:
                        continue
                    bucket = table.setdefault(
                        part_name,
                        {
                            "idle": 0,
                            "alloc": 0,
                            "down": 0,
                            "total": 0,
                        },
                    )
                    bucket["total"] += count
                    if state == "idle":
                        bucket["idle"] += count
                    elif state in ("allocated", "mixed", "completing"):
                        bucket["alloc"] += count
                    elif state in (
                        "down",
                        "drained",
                        "draining",
                        "fail",
                        "failing",
                        "maint",
                        "reserved",
                    ):
                        bucket["down"] += count
                if table:
                    sorted_parts = sorted(
                        table.items(),
                        key=lambda kv: kv[1]["total"],
                        reverse=True,
                    )[:4]
                    out["partitions"] = dict(sorted_parts)
        except Exception:
            pass

    return out


# todo#418: agent decision-transparency classifier. Mirrors the state
# labels the fleet-prompt-actuator + scitex_agent_container.runtimes.prompts
# module use, but inlined so agent_meta.py stays dependency-free. The
# classifier runs on every push (~30s), reads the pane tail, and emits a
# stable label + verbatim stuck-prompt text so the hub Agents tab can
# render a badge + expand the prompt ywatanabe needs to see.
_COMPOSE_CHEVRON = "❯"
_PROGRESS_MARKERS = ("esc to interrupt",)
_AUTH_MARKERS = ("/login", "Invalid API key", "authentication failed")
_BYPASS_MARKERS = ("Bypass Permissions", "2. Yes, I accept")
_DEVCHAN_MARKERS = ("1. I am using this for local development",)
_YN_MARKERS = ("y/n", "[y/N]", "[Y/n]")


def _extract_compose_text(tail: str) -> str:
    """Return the content after the `❯` chevron on the last compose line, or ''."""
    compose = ""
    for line in tail.splitlines()[-12:]:
        stripped = line.lstrip()
        if stripped.startswith(_COMPOSE_CHEVRON):
            rest = stripped[len(_COMPOSE_CHEVRON) :]
            compose = rest.lstrip(" \t\u00a0").rstrip()
    return compose


def _classify_pane_state(tail_clean: str, full_pane: str) -> str:
    """Classify the agent's current pane state into one of:
    running / compose_pending_unsent / bypass_permissions_prompt /
    dev_channels_prompt / y_n_prompt / auth_error / idle / ""

    Conservative — returns "" when we can't confidently classify.
    The full_pane string is the raw ~30-line capture used for marker
    scans; tail_clean is the channel-inbound-stripped tail used for
    compose-box detection (so ← scitex-orochi lines don't fool us).
    """
    if not full_pane and not tail_clean:
        return ""
    hay = (full_pane or "") + "\n" + (tail_clean or "")
    if any(m in hay for m in _PROGRESS_MARKERS):
        return "running"
    if any(m in hay for m in _AUTH_MARKERS):
        return "auth_error"
    if all(m in hay for m in _BYPASS_MARKERS):
        return "bypass_permissions_prompt"
    if any(m in hay for m in _DEVCHAN_MARKERS):
        return "dev_channels_prompt"
    if any(m in hay for m in _YN_MARKERS):
        return "y_n_prompt"
    compose = _extract_compose_text(tail_clean)
    if len(compose) >= 3 and not compose.startswith("> "):
        return "compose_pending_unsent"
    return "idle"


def _extract_stuck_prompt(tail_clean: str, full_pane: str) -> str:
    """Return the verbatim stuck-prompt text the agent is blocked on.

    Empty string when the agent isn't stuck. For `compose_pending_unsent`
    we return the chevron-line content; for the other prompt classes
    (bypass/dev-channels/y_n) we return a short excerpt from the tail
    containing the marker line, so ywatanabe can see *exactly* what text
    the agent is facing.
    """
    state = _classify_pane_state(tail_clean, full_pane)
    if state in ("running", "idle", ""):
        return ""
    if state == "compose_pending_unsent":
        return _extract_compose_text(tail_clean)[:500]
    hay_lines = (tail_clean or "").splitlines()[-12:]
    return "\n".join(hay_lines)[:500]


def collect(agent: str) -> dict:
    """Return the same dict that ``main`` would print, without printing.

    Extends the legacy payload with fields required by the Orochi
    Agents-tab dashboard (todo#213):
        pid, ppid, started_at, workdir, project, machine, skills_loaded,
        runtime, version, subagent_count.
    Any field that can't be determined is omitted or left empty so the
    receiver can degrade gracefully.
    """
    multiplexer = detect_multiplexer(agent)
    if not multiplexer:
        return {"agent": agent, "alive": False, "multiplexer": ""}

    # Pane content -- subagent count from status bar AND the last
    # non-empty visible line so the Agents tab can show what the agent
    # is *literally typing right now*. ywatanabe at msg#6575 said the
    # tab "ちかちかしすぎてわからん、その割に tmux で最後の行取ってない"
    # — he wants the live tail of the pane in each card, not just the
    # JSONL-derived tool name. -J joins wrapped lines so a long
    # command isn't reported as several short fragments.
    # Capture an extra ~30 lines of scrollback so we have real context,
    # not just the visible bottom strip. ywatanabe at msg#6587 said the
    # last single action alone is pointless — he wants the recent flow.
    pane = (
        subprocess.run(
            # todo#47 — bump scrollback depth from 30 to 500 lines so
            # the hub detail endpoint can expose a ``pane_tail_full``
            # field for the web-terminal viewer. The ~10-line
            # ``pane_tail_block`` keeps its original semantics below
            # (stuck-detection + compact UI), so classifiers aren't
            # perturbed. The full view is the new user-facing surface.
            ["tmux", "capture-pane", "-t", agent, "-p", "-J", "-S", "-500", "-E", "-"],
            capture_output=True,
            text=True,
        ).stdout
        if multiplexer == "tmux"
        else ""
    )
    pane_tail = ""  # last interesting single line (legacy field)
    pane_tail_block = ""  # last ~10 interesting lines (raw — keeps channel inbound for WS-alive proof)
    pane_tail_block_clean = ""  # same as block but stripped of channel inbound (for stuck-detection / state classifier)
    pane_tail_full = (
        ""  # up to 500 filtered lines, trimmed to 32 KB (todo#47 web-terminal tier)
    )

    def _is_channel_inbound_line(s: str) -> bool:
        """ywatanabe msg#10657 / #10677: incoming Orochi channel pushes
        appear in the pane as `← scitex-orochi · sender: ...` (then
        wrapped continuation, then `⎿ ...` reaction/result indent lines).
        These are NOT agent activity — they're fan-out from other agents
        — but they change the pane each tick so a hash-diff "is this
        agent moving?" check sees them as activity and reports the agent
        as healthy when it's actually wedged. The CLEAN view filters
        them out so stuck-detection / classifier work on agent output
        only. The RAW view keeps them so we can still verify "WS still
        delivering messages" as a separate signal."""
        if "← scitex-orochi" in s:
            return True
        # The two-line wrapped continuation of `← scitex-orochi` blocks
        # often starts with whitespace + ⎿ indent; treat those as inbound
        # too. Loose match — false-positive on legit `⎿  Done` is
        # acceptable since clean view is for diff-based stuck check, not
        # for full-fidelity rendering.
        if s.startswith("⎿"):
            return True
        return False

    if pane:
        kept: list[str] = []
        kept_clean: list[str] = []
        kept_full: list[str] = []  # full-scrollback for todo#47 web-terminal viewer
        for raw_line in reversed(pane.splitlines()):
            stripped = raw_line.strip()
            if not stripped:
                continue
            # Skip the box-drawing chrome and hint banners.
            if stripped.startswith("─") or stripped.startswith("⏵"):
                continue
            if "bypass permissions on" in stripped:
                continue
            if stripped.startswith("↑↓") or stripped.startswith("Esc to"):
                continue
            line = stripped[:160]
            # Full view keeps every interesting line up to the scrollback
            # cap we captured (500 lines). 32 KB is a generous ceiling —
            # well under WS frame limits, but enough for ~400-line Claude
            # Code transcripts with long MCP tool outputs.
            if len(kept_full) < 500:
                kept_full.append(line)
            if len(kept) < 10:
                kept.append(line)
                if not _is_channel_inbound_line(line):
                    kept_clean.append(line)
            if len(kept_full) >= 500:
                break
        if kept:
            pane_tail = kept[0]
            pane_tail_block = "\n".join(reversed(kept))
            # Trim clean to its own 10-line cap to match pane_tail_block size.
            pane_tail_block_clean = "\n".join(reversed(kept_clean[:10]))
        if kept_full:
            pane_tail_full = "\n".join(reversed(kept_full))
            # Hard-cap the payload so a pathological pane can't bloat the
            # heartbeat. Trim from the head (oldest) so the tail (latest
            # activity) is preserved.
            if len(pane_tail_full) > 32 * 1024:
                pane_tail_full = pane_tail_full[-32 * 1024 :]
    subagents = 0
    m = re.search(r"(\d+) local agent", pane)
    if m:
        subagents = int(m.group(1))

    # Parse Claude Code statusline for quota and context info.
    # Statusline format (claude-hud):
    #   [Opus 4.6 (1M context) | Max] ████░░░░░░ 39% | ███████░░░ 73% (1h 8m / 5h)
    #   █████░░░░░ 54% (5d 15h / 7d) | wyusuuke@gmail.com
    #
    # Reference: https://github.com/jarrodwatts/claude-hud
    # Upstream claude-hud reads its numbers from Claude Code's native
    # statusline stdin JSON (stdin.context_window.used_percentage,
    # rate_limits.{five_hour,seven_day}.used_percentage — see
    # claude-hud/src/stdin.ts). Scraping the rendered bars is a
    # downgrade from that source, but we do it here because this
    # script never has access to the stdin payload Claude Code only
    # hands to its registered statusline command. The authoritative
    # replacement lives in scitex-agent-container (see
    # `scitex-agent-container status --json`) which should eventually
    # register its own statusline hook and persist the JSON to disk so
    # this client side can stop regex-parsing pane output entirely.
    statusline_context_pct = None
    quota_5h_pct = None
    quota_5h_remaining = ""
    quota_weekly_pct = None
    quota_weekly_remaining = ""
    statusline_model = ""
    account_email = ""

    # Extract model from statusline: [Model Name (context) | Mode]
    m_model = re.search(r"\[([^\]]+)\]", pane_tail_block if pane_tail_block else "")
    if m_model:
        statusline_model = m_model.group(1).strip()

    # Extract account email
    m_email = re.search(
        r"([\w.+-]+@[\w.-]+\.\w+)", pane_tail_block if pane_tail_block else ""
    )
    if m_email:
        account_email = m_email.group(1)

    # Extract percentages from statusline bars: ██░░ NN% (Xh Ym / 5h)
    # Pattern: percentage followed by optional time info in parens
    pct_matches = re.findall(
        r"[█░▓▒]{2,}\s+(\d+)%(?:\s*\(([^)]+)\))?",
        pane_tail_block if pane_tail_block else "",
    )
    # First bar = context, second = 5h quota, third = weekly quota
    if len(pct_matches) >= 1:
        statusline_context_pct = float(pct_matches[0][0])
    if len(pct_matches) >= 2:
        quota_5h_pct = float(pct_matches[1][0])
        quota_5h_remaining = pct_matches[1][1] if pct_matches[1][1] else ""
    if len(pct_matches) >= 3:
        quota_weekly_pct = float(pct_matches[2][0])
        quota_weekly_remaining = pct_matches[2][1] if pct_matches[2][1] else ""

    # Locate latest transcript JSONL (same algorithm as main)
    # Path must match the actual workspace path on this OS
    home = str(Path.home())
    workspace = f"{home}/.dotfiles/src/.scitex/orochi/workspaces/{agent}"
    encoded = workspace.replace("/", "-").replace(".", "-")
    encoded = re.sub(r"-{3,}", "--", encoded)
    proj_dir = Path.home() / ".claude" / "projects" / encoded
    jsonls = (
        sorted(proj_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if proj_dir.is_dir()
        else []
    )

    context_pct = 0.0
    current_tool = ""
    last_activity = ""
    model = ""
    started_at = ""
    # Recent actions populated below if a JSONL transcript is found.
    recent_actions: list[dict] = []

    if jsonls:
        jsonl = jsonls[0]
        try:
            lines = jsonl.read_text().splitlines()
        except Exception:
            lines = []
        tail = lines[-50:]

        # started_at = mtime of earliest jsonl for this project (ISO UTC)
        try:
            from datetime import datetime, timezone

            earliest = min(jsonls, key=lambda p: p.stat().st_mtime)
            started_at = datetime.fromtimestamp(
                earliest.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except Exception:
            pass

        for line in reversed(tail):
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") == "assistant" and "message" in obj:
                msg = obj["message"]
                if not model:
                    model = msg.get("model", "")
                if not last_activity:
                    last_activity = obj.get("timestamp", "")
                u = msg.get("usage", {})
                total = (
                    u.get("input_tokens", 0)
                    + u.get("cache_read_input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0)
                )
                context_pct = round((total / 1_000_000) * 100, 1)
                break

        # Pick the most recent meaningful tool use, skipping the
        # mcp__scitex-orochi__* housekeeping tools (reply / react /
        # status / history / context / health / etc.) — those are how
        # the agent talks to the chat hub, NOT what the agent is
        # actually working on. Showing them as current_task makes every
        # idle agent look frozen on "reply" forever, which is the
        # exact UX failure ywatanabe flagged at msg#6546 / msg#6551.
        # For the picked tool, build a short input preview so the
        # Agents tab card shows e.g. "Bash: docker compose build"
        # instead of just "Bash".
        SKIP_TOOLS = {
            "mcp__scitex-orochi__reply",
            "mcp__scitex-orochi__react",
            "mcp__scitex-orochi__status",
            "mcp__scitex-orochi__history",
            "mcp__scitex-orochi__context",
            "mcp__scitex-orochi__health",
            "mcp__scitex-orochi__upload_media",
            "mcp__scitex-orochi__download_media",
            "mcp__scitex-orochi__rsync_media",
            "mcp__scitex-orochi__rsync_status",
            "mcp__scitex-orochi__self_command",
            "mcp__scitex-orochi__subagents",
            "mcp__scitex-orochi__task",
            "TodoWrite",
        }

        def _preview_for(tool_name: str, tool_input: dict) -> str:
            """Return a short label for the tool + its first arg."""
            if not isinstance(tool_input, dict):
                return tool_name
            short = tool_name
            arg = ""
            if tool_name == "Bash":
                arg = tool_input.get("command") or tool_input.get("description") or ""
            elif tool_name in ("Read", "Edit", "Write", "NotebookEdit"):
                arg = tool_input.get("file_path") or ""
            elif tool_name == "Glob":
                arg = tool_input.get("pattern") or ""
            elif tool_name == "Grep":
                arg = tool_input.get("pattern") or ""
            elif tool_name == "WebFetch":
                arg = tool_input.get("url") or ""
            elif tool_name == "WebSearch":
                arg = tool_input.get("query") or ""
            elif tool_name == "Agent":
                arg = tool_input.get("description") or ""
            elif tool_name.startswith("mcp__"):
                short = tool_name.split("__", 2)[-1]
                arg = (
                    tool_input.get("query")
                    or tool_input.get("text")
                    or tool_input.get("description")
                    or ""
                )
            else:
                # Generic: try common arg keys
                arg = (
                    tool_input.get("description")
                    or tool_input.get("query")
                    or tool_input.get("name")
                    or ""
                )
            if arg:
                arg = " ".join(arg.split())[:80]
                return f"{short}: {arg}"
            return short

        for line in reversed(tail):
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") == "assistant":
                content = obj.get("message", {}).get("content", [])
                for c in content:
                    if c.get("type") != "tool_use":
                        continue
                    name = c.get("name", "")
                    if name in SKIP_TOOLS:
                        continue
                    current_tool = _preview_for(name, c.get("input") or {})
                    break
                if current_tool:
                    break

        # Recent 10 actions with timestamps. ywatanabe at msg#6608 wants
        # the card to feel like a mini activity log per agent: a vertical
        # list of "16:05:02 Bash: docker compose build" etc. Skips the
        # SKIP_TOOLS housekeeping calls and pulls the last ~200 lines
        # of the JSONL so we don't miss anything in a busy turn.
        recent_actions: list[dict] = []
        wide_tail = lines[-200:] if lines else []
        for line in reversed(wide_tail):
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "assistant":
                continue
            ts = obj.get("timestamp", "")
            content = obj.get("message", {}).get("content", [])
            for c in content:
                if c.get("type") != "tool_use":
                    continue
                tname = c.get("name", "")
                if tname in SKIP_TOOLS:
                    continue
                recent_actions.append(
                    {
                        "ts": ts,
                        "preview": _preview_for(tname, c.get("input") or {}),
                    }
                )
                if len(recent_actions) >= 10:
                    break
            if len(recent_actions) >= 10:
                break
        # Newest first → reverse to oldest first so the UI can render
        # top-down chronologically.
        recent_actions.reverse()

    # Process info: first claude child pid under the multiplexer session
    pid = 0
    ppid = 0
    try:
        if multiplexer == "tmux":
            out = (
                subprocess.run(
                    ["tmux", "list-panes", "-t", agent, "-F", "#{pane_pid}"],
                    capture_output=True,
                    text=True,
                )
                .stdout.strip()
                .splitlines()
            )
            if out:
                ppid = int(out[0])
                # Find a descendant claude process
                ps = (
                    subprocess.run(
                        ["pgrep", "-P", str(ppid), "-f", "claude"],
                        capture_output=True,
                        text=True,
                    )
                    .stdout.strip()
                    .splitlines()
                )
                if ps:
                    pid = int(ps[0])
                else:
                    pid = ppid
    except Exception:
        pass

    # Skills loaded: read CLAUDE.md under the workspace for ```skills fences.
    skills_loaded: list[str] = []
    try:
        cmd = Path(workspace) / "CLAUDE.md"
        if cmd.is_file():
            text = cmd.read_text()
            for block in re.findall(r"```skills\n(.*?)\n```", text, re.DOTALL):
                for ln in block.splitlines():
                    ln = ln.strip()
                    if ln and not ln.startswith("#"):
                        skills_loaded.append(ln)
    except Exception:
        pass

    project = agent
    # Canonical fleet label — single source of truth is
    # shared/config.yaml::hostname_aliases. Resolution chain (first wins):
    #   1. $SCITEX_OROCHI_HOSTNAME
    #   2. hostname_aliases[hostname -s] from shared/config.yaml
    #   3. hostname -s (identity fallback)
    # This matches config._host.resolve_hostname() on the sac side and the
    # shared/scripts/resolve-hostname helper used by bootstrap + shell
    # scripts, so the hub always sees a consistent "mba" / "nas" /
    # "spartan" / "ywata-note-win" regardless of raw OS hostname.
    machine = os.environ.get("SCITEX_OROCHI_HOSTNAME", "").strip()
    if not machine:
        raw_host = socket.gethostname().split(".")[0]
        try:
            import yaml as _yaml  # PyYAML ships with the fleet.

            cfg_path = Path.home() / ".scitex" / "orochi" / "shared" / "config.yaml"
            if cfg_path.exists():
                _cfg = _yaml.safe_load(cfg_path.read_text()) or {}
                _aliases = (_cfg.get("spec") or {}).get("hostname_aliases") or {}
                if isinstance(_aliases, dict) and raw_host in _aliases:
                    machine = str(_aliases[raw_host])
        except Exception:
            pass
        if not machine:
            machine = raw_host

    # MCP servers actually loaded by this agent's claude session — read
    # from the workspace's .mcp.json so the card can show "scitex-orochi,
    # PubMed, …" instead of "MCP info missing" (msg#6579 / msg#6580).
    mcp_servers: list[str] = []
    try:
        mcp_path = Path(workspace) / ".mcp.json"
        if mcp_path.is_file():
            doc = json.loads(mcp_path.read_text())
            servers = doc.get("mcpServers") or {}
            if isinstance(servers, dict):
                mcp_servers = sorted(servers.keys())
    except Exception:
        pass

    # CLAUDE.md head — first non-empty heading line so the card can show
    # the agent's role / mission at a glance (msg#6579).
    claude_md_head = ""
    # CLAUDE.md full — for the per-agent page CLAUDE.md viewer
    # (todo#460, ywatanabe msg#13050). Truncated to ~10000 chars to keep
    # the heartbeat payload bounded; the viewer renders the truncated
    # body and links to the canonical file path for the rest.
    claude_md_full = ""

    # todo#53: historically only head-* agents had a CLAUDE.md at
    # `<workspace>/CLAUDE.md`. Other roles (healer / skill-manager /
    # todo-manager / ...) either live under a legacy `mamba-<name>/`
    # directory, use the user's global `~/.claude/CLAUDE.md`, or have
    # the file placed in a nested `.claude/` folder. We now walk a
    # prioritised candidate list so the detail view has content for
    # every agent instead of only head.
    def _claude_md_candidates(ws: str) -> list[Path]:
        p = Path(ws) if ws else None
        home = Path.home()
        cands: list[Path] = []
        if p is not None:
            cands += [p / "CLAUDE.md", p / ".claude" / "CLAUDE.md"]
            if p.parent.name == "workspaces":
                # Legacy sibling directory: mamba-<role>-<host>/CLAUDE.md
                cands.append(p.parent / f"mamba-{p.name}" / "CLAUDE.md")
            # Project-level Claude config if the agent cwd is a git repo
            try:
                git_root = p
                while git_root != git_root.parent and not (git_root / ".git").exists():
                    git_root = git_root.parent
                if (git_root / ".git").exists():
                    cands.append(git_root / "CLAUDE.md")
            except Exception:
                pass
        cands += [home / ".claude" / "CLAUDE.md", home / "CLAUDE.md"]
        # Dedup preserving order.
        seen: set[str] = set()
        uniq: list[Path] = []
        for c in cands:
            key = str(c)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(c)
        return uniq

    for cmd in _claude_md_candidates(workspace):
        try:
            if cmd.is_file():
                text = cmd.read_text()
                for ln in text.splitlines():
                    ln_stripped = ln.strip()
                    if ln_stripped and not ln_stripped.startswith("```"):
                        claude_md_head = ln_stripped[:120]
                        break
                claude_md_full = text[:10000]
                break
        except Exception:
            continue

    # .mcp.json full — for the per-agent page .mcp.json viewer
    # (todo#460). Tokens are redacted (env values containing TOKEN /
    # SECRET / KEY substrings). Truncated to 10000 chars.
    mcp_json_full = ""

    # todo#53: same fallback logic for .mcp.json so non-head agents also
    # populate the MCP viewer.
    def _mcp_json_candidates(ws: str) -> list[Path]:
        p = Path(ws) if ws else None
        home = Path.home()
        cands: list[Path] = []
        if p is not None:
            cands += [p / ".mcp.json"]
            if p.parent.name == "workspaces":
                cands.append(p.parent / f"mamba-{p.name}" / ".mcp.json")
            try:
                git_root = p
                while git_root != git_root.parent and not (git_root / ".git").exists():
                    git_root = git_root.parent
                if (git_root / ".git").exists():
                    cands.append(git_root / ".mcp.json")
            except Exception:
                pass
        cands += [home / ".mcp.json"]
        seen: set[str] = set()
        uniq: list[Path] = []
        for c in cands:
            key = str(c)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(c)
        return uniq

    def _redact_secrets(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if isinstance(v, str) and any(
                    tag in k.upper() for tag in ("TOKEN", "SECRET", "KEY", "PASSWORD")
                ):
                    out[k] = "***REDACTED***"
                else:
                    out[k] = _redact_secrets(v)
            return out
        if isinstance(obj, list):
            return [_redact_secrets(x) for x in obj]
        return obj

    for mcp_path in _mcp_json_candidates(workspace):
        try:
            if not mcp_path.is_file():
                continue
            doc = json.loads(mcp_path.read_text())
            redacted = _redact_secrets(doc)
            mcp_json_full = json.dumps(redacted, indent=2)[:10000]
            break
        except Exception:
            continue

    return {
        "agent": agent,
        "alive": True,
        "multiplexer": multiplexer,
        "subagents": subagents,
        "subagent_count": subagents,
        "context_pct": statusline_context_pct
        if statusline_context_pct is not None
        else context_pct,
        "current_tool": current_tool,
        "current_task": current_tool,
        "quota_5h_pct": quota_5h_pct,
        "quota_5h_remaining": quota_5h_remaining,
        "quota_weekly_pct": quota_weekly_pct,
        "quota_weekly_remaining": quota_weekly_remaining,
        "statusline_model": statusline_model,
        "account_email": account_email,
        # Live tail of the agent's tmux pane — what the user would see
        # if they attached right now. Bypasses the JSONL transcript so
        # mid-tool-call activity (e.g. a streaming Bash command) shows
        # up. msg#6575 ("tmux で最後の行取ってない") / msg#6582 /
        # msg#6587 (single line is pointless — needs the recent flow).
        "pane_tail": pane_tail,
        "pane_tail_block": pane_tail_block,
        # todo#47 — ~500 filtered lines of tmux scrollback for the
        # agent-detail "Full pane" toggle in the Agents tab. 32 KB
        # cap applied above.
        "pane_tail_full": pane_tail_full,
        # ywatanabe msg#10657/10677: same as pane_tail_block but with
        # `← scitex-orochi · ...` channel inbound + `⎿` continuation
        # lines stripped, so consumers (fleet_watch.sh stuck-cycle
        # counter, pane_state.py classifier) can compute "did the agent
        # actually do anything?" without being fooled by inbound chatter.
        "pane_tail_block_clean": pane_tail_block_clean,
        "recent_actions": recent_actions,
        "last_activity": last_activity,
        # If the most recent assistant turn carried no real model label
        # (empty or a <synthetic>-style placeholder from compacted
        # summaries), fall back to the env var the runtime set at spawn.
        # The env is fetched from the claude process's own /proc/<pid>/environ
        # (the push script's own environment does NOT carry per-agent model
        # — each agent has its own model in its own process env).
        "model": (
            model
            if model and not model.startswith("<")
            # Linux-only: peek at /proc/<pid>/environ for the real
            # model env the runtime set at spawn.
            else (
                _read_process_env(
                    pid, ("SCITEX_AGENT_CONTAINER_MODEL", "SCITEX_OROCHI_MODEL")
                )
                # Darwin fallback: /proc doesn't exist. Check the pusher's
                # own env — on mba the tmux launcher exports
                # SCITEX_OROCHI_MODEL before spawning both claude and the
                # heartbeat helper, so they share the same env. Without
                # this the heartbeat keeps pushing "<synthetic>" (incident:
                # head-mba detail card, ywatanabe msg 2026-04-18 20:09).
                or os.environ.get("SCITEX_AGENT_CONTAINER_MODEL", "").strip()
                or os.environ.get("SCITEX_OROCHI_MODEL", "").strip()
                or model
            )
        ),
        "pid": pid,
        "ppid": ppid,
        "started_at": started_at,
        "workdir": workspace,
        "project": project,
        "machine": machine,
        # todo#55: canonical FQDN for display next to the short machine
        # label in the dashboard (e.g. "spartan (spartan.hpc.unimelb.edu.au)",
        # "mba (Yusukes-MacBook-Air.local)").
        # _resolve_canonical_hostname() prefers socket.getfqdn() on Linux but
        # falls back to socket.gethostname() on macOS, where getfqdn() often
        # resolves the IPv6 loopback PTR to `1.0.0.0...ip6.arpa` instead of
        # the user-meaningful `*.local` name. The dashboard collapses to the
        # short label when canonical is empty or identical.
        "hostname_canonical": _resolve_canonical_hostname(),
        "skills_loaded": skills_loaded,
        "mcp_servers": mcp_servers,
        "claude_md_head": claude_md_head,
        # todo#460 full-content fields for the Agents tab viewer.
        "claude_md": claude_md_full,
        "mcp_json": mcp_json_full,
        # todo#418: agent decision-transparency — classifier label + verbatim
        # stuck-prompt text. Computed from pane_tail_block_clean below.
        "pane_state": _classify_pane_state(pane_tail_block_clean, pane),
        "stuck_prompt_text": _extract_stuck_prompt(pane_tail_block_clean, pane),
        # scitex-orochi #187 / #59 — hook-event ring buffer summary
        # from scitex-agent-container. Unpacked as top-level keys so
        # push_all()'s whitelist can forward each one verbatim.
        **_collect_hook_events(agent),
        "runtime": "claude-code",
        "version": os.environ.get("SCITEX_OROCHI_AGENT_META_VERSION", "0.1"),
        # Machine resource snapshot (todo#329 — Machines tab populate).
        # hub/views/api.py:api_resources reads .metrics.{cpu_count,
        # mem_used_percent, ...} from each agent heartbeat to render the
        # Machines tab cards. Without this, all values render as 0%.
        "metrics": collect_machine_metrics(),
        # SLURM compute snapshot (todo#59). None on non-HPC hosts so the
        # Machines tab can hide the SLURM card cleanly. Populated on
        # head-spartan with running/pending counts + per-partition node
        # state buckets.
        "slurm": collect_slurm_status(),
    }


def _read_process_env(pid: int, keys: tuple[str, ...]) -> str:
    """Return the first non-empty env value found in /proc/<pid>/environ.

    Each agent process (claude-code) carries its own env with the model
    label the runtime set at spawn — but the pusher itself runs under a
    systemd/launchd timer that has a different env. To give the dashboard
    an accurate per-agent model (not the pusher's env), peek at the
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


def _http_post_json(url: str, payload: dict, timeout: float = 5.0) -> tuple[int, str]:
    """POST JSON using requests if available, else stdlib urllib."""
    data = json.dumps(payload).encode("utf-8")
    try:
        import requests  # type: ignore

        r = requests.post(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        return r.status_code, r.text[:200]
    except ImportError:
        pass
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]


def push_all(url=None, token=None) -> int:
    """Collect metadata for every local agent session and POST to the hub.

    Returns number of successful heartbeats. Never raises.
    """
    if os.environ.get("SCITEX_OROCHI_REGISTRY_DISABLE") == "1":
        log.info("push disabled via SCITEX_OROCHI_REGISTRY_DISABLE=1")
        return 0
    base = url or os.environ.get("SCITEX_OROCHI_URL_HTTP", "https://scitex-orochi.com")
    tok = token or os.environ.get("SCITEX_OROCHI_TOKEN", "")
    if not tok:
        log.warning("push skipped: no SCITEX_OROCHI_TOKEN in env")
        return 0
    endpoint = base.rstrip("/") + "/api/agents/register/"

    # todo#265: read Claude Code OAuth public metadata ONCE per push
    # cycle (not per agent) — it's the same for every local agent on
    # this host. Whitelist-only; never touches .credentials.json.
    oauth_meta = read_oauth_metadata()

    ok = 0
    for agent in _list_local_agents():
        try:
            meta = collect(agent)
            if not meta.get("alive"):
                continue
            payload = {
                "token": tok,
                "name": meta["agent"],
                "agent_id": meta["agent"],
                "role": "agent",
                "machine": meta.get("machine", ""),
                "hostname_canonical": meta.get("hostname_canonical", ""),
                "model": meta.get("model", ""),
                "multiplexer": meta.get("multiplexer", ""),
                "project": meta.get("project", ""),
                "workdir": meta.get("workdir", ""),
                "pid": meta.get("pid") or 0,
                "ppid": meta.get("ppid") or 0,
                "context_pct": meta.get("context_pct"),
                "subagent_count": int(meta.get("subagent_count") or 0),
                "skills_loaded": list(meta.get("skills_loaded") or []),
                "started_at": meta.get("started_at", ""),
                "version": meta.get("version", ""),
                "runtime": meta.get("runtime", ""),
                "current_task": meta.get("current_task", ""),
                # Intentionally no "channels" key. Subscriptions are
                # server-authoritative (ChannelMembership rows); heartbeats
                # must not clobber them. New agents start with no
                # subscriptions — the user opts in via the dashboard.
                # Observability fields for the per-agent detail view
                # (/api/agents/<name>/detail/). Without these the hub
                # shows empty CLAUDE.md / .mcp.json / terminal output
                # panels even though the agent collects them locally.
                "claude_md": meta.get("claude_md", ""),
                "mcp_json": meta.get("mcp_json", ""),
                "mcp_servers": list(meta.get("mcp_servers") or []),
                "pane_tail": meta.get("pane_tail", ""),
                "pane_tail_block": meta.get("pane_tail_block", ""),
                # todo#47 — full scrollback for the "Expand" toggle in
                # the agent detail pane viewer.
                "pane_tail_full": meta.get("pane_tail_full", ""),
                "pane_state": meta.get("pane_state", ""),
                "stuck_prompt_text": meta.get("stuck_prompt_text", ""),
                # scitex-orochi #187 / #59 — forward the hook-event
                # ring buffer summary so the Agents tab's Last tool /
                # Last MCP / Last action rows populate. Without this,
                # collect() gathers them but the whitelist drops them
                # before they reach the hub (same trap as #232 for
                # pane_tail_full).
                "recent_tools": meta.get("recent_tools") or [],
                "recent_prompts": meta.get("recent_prompts") or [],
                "tool_counts": meta.get("tool_counts") or {},
                "last_tool_name": meta.get("last_tool_name") or "",
                "last_tool_at": meta.get("last_tool_at") or "",
                "last_mcp_tool_name": meta.get("last_mcp_tool_name") or "",
                "last_mcp_tool_at": meta.get("last_mcp_tool_at") or "",
                "last_action_name": meta.get("last_action_name") or "",
                "last_action_at": meta.get("last_action_at") or "",
                "last_action_outcome": meta.get("last_action_outcome") or "",
                "last_action_elapsed_s": meta.get("last_action_elapsed_s"),
                "p95_elapsed_s_by_action": meta.get("p95_elapsed_s_by_action") or {},
            }
            # todo#265: merge OAuth account public metadata into the
            # heartbeat payload. All 9 keys are whitelist-extracted
            # from ~/.claude.json — no tokens/secrets/credentials.
            payload.update(oauth_meta)
            status, body = _http_post_json(endpoint, payload)
            if 200 <= status < 300:
                ok += 1
                log.info(
                    "pushed %s ctx=%s%% subs=%s pid=%s",
                    agent,
                    meta.get("context_pct"),
                    meta.get("subagent_count"),
                    meta.get("pid"),
                )
            else:
                log.warning("push %s -> HTTP %s: %s", agent, status, body)
        except Exception as e:
            log.warning("push %s failed: %s", agent, e)
    return ok


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--push":
        url = None
        token = None
        i = 1
        while i < len(args):
            if args[i] == "--url" and i + 1 < len(args):
                url = args[i + 1]
                i += 2
            elif args[i] == "--token" and i + 1 < len(args):
                token = args[i + 1]
                i += 2
            else:
                i += 1
        n = push_all(url=url, token=token)
        print(json.dumps({"pushed": n}))
        sys.exit(0)
    if len(args) != 1:
        print(
            "Usage: agent_meta.py <agent>  |  agent_meta.py --push [--url URL] [--token TOKEN]",
            file=sys.stderr,
        )
        sys.exit(2)
    main(args[0])
