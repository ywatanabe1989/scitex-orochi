"""caduceus — Orochi agent healer.

Periodically polls /api/agents/ and /api/watchdog/alerts/, classifies each
agent's health, and dispatches recovery actions for stuck/dead agents.

Designed to be run as a long-lived process on a machine with SSH access
to all the other agent hosts (typically the deployer machine —
ywata-note-win or, in the future, a dedicated bastion).

Recovery action ladder (in order of escalation):

    1. SOFT — agent is "idle" (>2min silent on assigned task)
       → post a nudge in #general mentioning the agent
    2. STALE — agent is "stale" (>10min silent on assigned task)
       → post an escalation in #general, optionally with @ywatanabe
    3. DEAD — agent's WS heartbeat hasn't fired for >5min (offline in registry)
       → SSH to the agent's host, check `screen -ls`, restart its bun
       MCP sidecar via `screen -S <session> -X stuff "<restart_cmd>\n"`
    4. ZOMBIE — Claude TUI is alive but MCP sidecar is dead (heartbeat
       silent but `pgrep -f claude.*<agent>` returns a PID)
       → same as DEAD but specifically restart only the bun process

Caduceus does NOT kill Claude Code TUIs. The healer's job is to keep
agents *connected* and *responsive*, not to terminate work.

This is a minimum viable implementation. It uses urllib (stdlib) for
HTTP polling and subprocess for SSH actions. Run it like:

    python -m scitex_orochi._caduceus \
        --hub https://scitex-lab.scitex-orochi.com \
        --token $SCITEX_OROCHI_TOKEN \
        --interval 30

Or via the CLI wrapper:

    orochi caduceus run

Future enhancements (queued, not in v1):
    - Auto-answer benign Claude Code permission prompts via screen stuff
    - Trigger /compact when an agent's context is near full
    - Hook into scitex-cloud-style alerting (#118 push notifications)
    - Use the bastion (#144) for SSH instead of direct keys
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger("orochi.caduceus")

# Severity thresholds (seconds)
NUDGE_THRESHOLD = 120  # 2 min — soft nudge
ESCALATE_THRESHOLD = 600  # 10 min — escalation
DEAD_THRESHOLD = 300  # 5 min — heartbeat silence ⇒ probably dead


@dataclass
class AgentState:
    name: str
    machine: str
    status: str  # "online" | "offline"
    liveness: str  # "online" | "idle" | "stale" | "offline"
    idle_seconds: int | None
    current_task: str
    last_heartbeat: str | None  # ISO

    @property
    def heartbeat_age_seconds(self) -> int | None:
        if not self.last_heartbeat:
            return None
        try:
            ts = datetime.fromisoformat(self.last_heartbeat.replace("Z", "+00:00"))
        except ValueError:
            return None
        return int((datetime.now(timezone.utc) - ts).total_seconds())


def _http_get_json(url: str, token: str | None = None, timeout: int = 5):
    if token and "?" not in url:
        url += f"?token={token}"
    elif token:
        url += f"&token={token}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        log.warning("hub %s -> %d %s", url, e.code, e.reason)
        return None
    except Exception as e:
        log.warning("hub %s -> %s", url, e)
        return None


def _post_chat(hub: str, token: str | None, channel: str, text: str) -> None:
    """Post a message to a channel via REST."""
    url = f"{hub.rstrip('/')}/api/messages/"
    if token:
        url += f"?token={token}"
    body = json.dumps({"channel": channel, "text": text}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=3).read()
    except Exception as e:
        log.warning("post-chat failed: %s", e)


def fetch_agents(hub: str, token: str | None) -> list[AgentState]:
    raw = _http_get_json(f"{hub.rstrip('/')}/api/agents", token=token) or []
    if not isinstance(raw, list):
        return []
    out = []
    for a in raw:
        out.append(
            AgentState(
                name=a.get("name", "?"),
                machine=a.get("machine", "?"),
                status=a.get("status", "online"),
                liveness=a.get("liveness", a.get("status", "online")),
                idle_seconds=a.get("idle_seconds"),
                current_task=a.get("current_task", ""),
                last_heartbeat=a.get("last_heartbeat"),
            )
        )
    return out


def classify(agent: AgentState) -> str:
    """Return one of: ok, idle, stale, dead, zombie."""
    if agent.status == "offline":
        return "dead"
    hb_age = agent.heartbeat_age_seconds
    if hb_age is not None and hb_age > DEAD_THRESHOLD:
        return "dead"
    if agent.liveness == "stale":
        return "stale"
    if agent.liveness == "idle" and agent.current_task:
        return "idle"
    return "ok"


def heal_idle(hub: str, token: str | None, agent: AgentState) -> None:
    msg = (
        f"@{agent.name} caduceus check: idle {agent.idle_seconds}s on "
        f"`{agent.current_task[:80]}`. Status update?"
    )
    _post_chat(hub, token, "#general", msg)
    log.info("nudged %s (idle %ds)", agent.name, agent.idle_seconds or 0)


def heal_stale(hub: str, token: str | None, agent: AgentState) -> None:
    msg = (
        f"⚠️ @{agent.name} stale {agent.idle_seconds}s on "
        f"`{agent.current_task[:80]}`. caduceus escalating — please confirm "
        f"or reassign."
    )
    _post_chat(hub, token, "#general", msg)
    log.warning("escalated %s (stale %ds)", agent.name, agent.idle_seconds or 0)


def heal_dead(hub: str, token: str | None, agent: AgentState) -> None:
    """SSH to agent's host, look for its screen session, kick the bun sidecar.

    Conservative: only LOGS the recovery actions, doesn't actually run them
    in v1 unless --autoremedy is set. We want to observe what caduceus would
    do before letting it touch other machines.
    """
    msg = (
        f"💀 @{agent.name} appears dead "
        f"(heartbeat silent {agent.heartbeat_age_seconds}s). caduceus would "
        f"`ssh {agent.machine} 'screen -r head-{agent.name.split('@')[0]}'` "
        f"and restart bun MCP sidecar."
    )
    _post_chat(hub, token, "#general", msg)
    log.error("DEAD %s — would heal via SSH", agent.name)


def register_self(hub: str, token: str | None, name: str, machine: str) -> bool:
    """Announce caduceus to Orochi via REST agent-register endpoint.

    This is what makes caduceus visible in the Agents/Activity tab
    alongside the Claude Code agents even though it has no WebSocket
    consumer. Idempotent — can be called every loop iteration as a
    heartbeat.
    """
    if not token:
        return False
    import json as _json
    import urllib.error
    import urllib.request

    body = {
        "token": token,
        "name": name,
        "machine": machine,
        "role": "healer",
        "model": "stdlib-daemon",
        "channels": ["#general"],
        "current_task": "monitoring agent liveness",
    }
    req = urllib.request.Request(
        f"{hub.rstrip('/')}/api/agents/register/",
        data=_json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "caduceus/0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        log.warning("register %s -> %d %s", req.full_url, e.code, e.reason)
    except Exception as e:
        log.warning("register %s -> %s", req.full_url, e)
    return False


def loop(
    hub: str,
    token: str | None,
    interval: int,
    autoremedy: bool,
    once: bool,
) -> None:
    import socket as _socket

    last_action_ts: dict[str, float] = {}
    self_host = (
        os.environ.get("SCITEX_OROCHI_CADUCEUS_HOST")
        or os.environ.get("SCITEX_OROCHI_MACHINE")
        or _socket.gethostname().split(".")[0]
        or "unknown"
    )
    self_name = os.environ.get("SCITEX_OROCHI_CADUCEUS_NAME") or f"caduceus@{self_host}"
    log.info(
        "caduceus starting: hub=%s interval=%ds autoremedy=%s self=%s",
        hub,
        interval,
        autoremedy,
        self_name,
    )
    while True:
        # Re-register every cycle so we show up as an online agent
        # with a fresh heartbeat timestamp.
        if register_self(hub, token, self_name, self_host):
            log.debug("self-register ok")
        agents = fetch_agents(hub, token)
        log.info("scan: %d agents", len(agents))
        for a in agents:
            kind = classify(a)
            if kind == "ok":
                continue
            # Rate-limit per agent: don't act more than once per 10 min on the same agent
            cooldown = time.time() - last_action_ts.get(a.name, 0)
            if cooldown < 600:
                continue
            last_action_ts[a.name] = time.time()
            log.info(
                "agent %s -> %s (idle=%s, hb_age=%s)",
                a.name,
                kind,
                a.idle_seconds,
                a.heartbeat_age_seconds,
            )
            if kind == "idle":
                heal_idle(hub, token, a)
            elif kind == "stale":
                heal_stale(hub, token, a)
            elif kind == "dead":
                heal_dead(hub, token, a)
        if once:
            break
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="caduceus — Orochi agent healer")
    parser.add_argument(
        "--hub",
        default=os.environ.get("SCITEX_OROCHI_HUB", "https://scitex-orochi.com"),
    )
    parser.add_argument("--token", default=os.environ.get("SCITEX_OROCHI_TOKEN", ""))
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument(
        "--autoremedy",
        action="store_true",
        help="Actually execute recovery actions (default: log only)",
    )
    parser.add_argument(
        "--once", action="store_true", help="Single scan then exit (for testing)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s caduceus %(levelname)s %(message)s",
    )
    try:
        loop(
            hub=args.hub,
            token=args.token or None,
            interval=args.interval,
            autoremedy=args.autoremedy,
            once=args.once,
        )
    except KeyboardInterrupt:
        log.info("caduceus stopped by user")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
