"""Caduceus greeting-ping health check — todo#168.

Today's caduceus classifies agents by heartbeat age + idle/stale on the
current task. None of those signals prove the agent is actually reading
incoming messages and capable of responding. An agent can have a fresh
heartbeat, a running Claude PID and a healthy MCP sidecar — and still
be "inbound-deaf" (MCP misconfigured, Claude loop stuck on an internal
thought, rate-limited, quota-exhausted).

The greeting ping fixes that by exercising the **full** inbound →
Claude → outbound loop: caduceus posts a targeted @-mention containing
an 8-char nonce, the agent's own `/loop` must reply with a short
`[pong:<nonce>]` within a timeout. Silence past the timeout classifies
the agent as conversationally-degraded / inbound-deaf, independent of
every other liveness signal.

This module is **pure state + parsing** — no hub I/O, no network, no
side-effects. The I/O wrapper lives in ``_caduceus.py`` / CLI. Keeping
the core free of I/O is what makes the unit tests in
``tests/test_caduceus_greeting.py`` cheap and deterministic.

Wire format (canonical — keep in sync with
``_skills/scitex-orochi/fleet-greeting-protocol.md`` and the
agent-side rule in ``fleet-communication-discipline.md``):

    caduceus -> #<channel>:  @<agent> [greeting:<8hex>]
    <agent>  -> #<channel>:  [pong:<8hex>]

Nonce format: 8 lowercase hex chars (32 bits of entropy) — same
convention as the PING-nonce broadcast protocol in
``fleet-random-nonce-ping-protocol.md`` so the two protocols share
tooling.
"""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

#: 8 lowercase hex chars. 32 bits of entropy = effectively collision-free
#: for any realistic in-flight window.
NONCE_REGEX = re.compile(r"\[pong:([0-9a-f]{8})\]")

#: Format string for the greeting message. ``agent`` is the @-target,
#: ``nonce`` is an 8-hex string. Do NOT add trailing punctuation — the
#: agent-side regex matches ``[greeting:<hex>]`` literally and nothing
#: more needs to be parseable.
GREETING_FORMAT = "@{agent} [greeting:{nonce}]"

#: Default timeout in seconds from send → pong. Matches rule #13
#: (one-minute responsiveness) in fleet-communication-discipline.
DEFAULT_TIMEOUT_S = 60

#: Hard upper bound on in-flight pings. Anything older than this is
#: garbage-collected regardless of timeout — prevents unbounded state
#: growth if the verifier loop stops pulling results.
MAX_PING_AGE_S = 3600


def new_nonce() -> str:
    """Return a fresh 8-char lowercase-hex nonce (32 bits of entropy).

    ``secrets.token_hex(4)`` returns exactly 8 lowercase hex chars; this
    is the same nonce format used by the broadcast PING-xxxx protocol
    documented in ``fleet-random-nonce-ping-protocol.md`` so verifiers
    can share regex tooling with this protocol.
    """
    return secrets.token_hex(4)


def format_greeting(agent: str, nonce: str | None = None) -> tuple[str, str]:
    """Return ``(message_body, nonce)``.

    ``nonce`` is optional for tests; when omitted, a fresh random nonce
    is drawn. The caller should persist the nonce into caduceus state
    before posting so a pong arriving inside the timeout window can be
    matched.
    """
    if nonce is None:
        nonce = new_nonce()
    # Validate caller-supplied nonces — wrong length / non-hex here
    # would silently produce a greeting the sidecar auto-responder
    # can't match.
    if not re.fullmatch(r"[0-9a-f]{8}", nonce):
        raise ValueError(f"nonce must be 8 lowercase hex chars, got {nonce!r}")
    return GREETING_FORMAT.format(agent=agent, nonce=nonce), nonce


def parse_pong(body: str) -> str | None:
    """Return the 8-hex nonce if ``body`` contains exactly one ``[pong:<hex>]``
    token, else ``None``.

    Free text around the token is allowed; the first match wins. This is
    intentionally lenient so an agent can include context ("[pong:xxx]
    after a /compact") without breaking the match — matches the permissive
    matching behaviour documented in ``fleet-random-nonce-ping-protocol.md``.
    """
    if not body:
        return None
    m = NONCE_REGEX.search(body)
    if not m:
        return None
    return m.group(1)


# ---------------------------------------------------------------------------
# In-flight state
# ---------------------------------------------------------------------------


@dataclass
class InFlightPing:
    """Single in-flight greeting. Fields match the dispatch/verify contract
    described in ``fleet-greeting-protocol.md``."""

    agent: str
    nonce: str
    sent_ts: float
    timeout_s: int = DEFAULT_TIMEOUT_S

    def is_expired(self, now: float) -> bool:
        return (now - self.sent_ts) > self.timeout_s


@dataclass
class GreetingState:
    """In-memory greeting-ping tracker.

    One instance lives on caduceus and is consulted every scan tick.
    Persistence across caduceus restarts is out of scope for Phase 1
    (a ~60 s window of forgotten in-flight pings is acceptable — the
    next cycle rediscovers all agents).
    """

    #: ``(agent, nonce) -> InFlightPing`` — keyed on both so two
    #: retry-pings to the same agent with different nonces don't collide.
    in_flight: dict[tuple[str, str], InFlightPing] = field(default_factory=dict)

    #: ``agent -> {"healthy" | "degraded", last_pong_ts, last_pong_nonce,
    #: consecutive_timeouts}``. Caduceus' health classifier reads this
    #: alongside the existing heartbeat-based signal.
    status: dict[str, dict] = field(default_factory=dict)

    def register_ping(
        self, agent: str, nonce: str, sent_ts: float, timeout_s: int = DEFAULT_TIMEOUT_S
    ) -> InFlightPing:
        ping = InFlightPing(
            agent=agent, nonce=nonce, sent_ts=sent_ts, timeout_s=timeout_s
        )
        self.in_flight[(agent, nonce)] = ping
        return ping

    def record_reply(self, body: str, recv_ts: float) -> InFlightPing | None:
        """If ``body`` contains a pong for an in-flight ping, mark the owning
        agent healthy, remove the ping from flight, and return the matched
        ``InFlightPing``. Otherwise return ``None``.

        Late pongs (arriving after the ping expired) are still accepted —
        they flip the agent back to healthy but caller may still want to
        log the elevated RTT. Unknown nonces are ignored (a stale pong from
        a previous caduceus run is expected noise).
        """
        nonce = parse_pong(body)
        if nonce is None:
            return None
        # Find the (agent, nonce) pair — a pong doesn't tell us which agent
        # it came from at the protocol level (free of @-mentions), so we
        # scan in-flight entries for the nonce. Nonce collision is 1/2^32.
        for key, ping in list(self.in_flight.items()):
            if key[1] == nonce:
                del self.in_flight[key]
                rtt_s = recv_ts - ping.sent_ts
                self.status[ping.agent] = {
                    "conversationally": "healthy",
                    "last_pong_ts": recv_ts,
                    "last_pong_nonce": nonce,
                    "last_rtt_s": rtt_s,
                    "consecutive_timeouts": 0,
                }
                return ping
        return None

    def sweep_expired(self, now: float) -> list[InFlightPing]:
        """Remove all in-flight pings that have timed out or aged past
        ``MAX_PING_AGE_S``. Mark their owning agents as ``inbound-deaf``
        and return the expired pings so the caller can emit escalation
        messages.
        """
        expired: list[InFlightPing] = []
        for key, ping in list(self.in_flight.items()):
            if ping.is_expired(now) or (now - ping.sent_ts) > MAX_PING_AGE_S:
                expired.append(ping)
                del self.in_flight[key]
                cur = self.status.get(ping.agent, {})
                consecutive = int(cur.get("consecutive_timeouts", 0)) + 1
                # Escalation ladder (issue#168 §6):
                # 1 miss  -> warn (degraded)
                # 2 miss  -> degraded
                # 3 miss+ -> inbound_deaf
                if consecutive >= 3:
                    label = "inbound_deaf"
                elif consecutive >= 2:
                    label = "degraded"
                else:
                    label = "warn"
                self.status[ping.agent] = {
                    "conversationally": label,
                    "last_timeout_ts": now,
                    "last_timeout_nonce": ping.nonce,
                    "consecutive_timeouts": consecutive,
                }
        return expired

    def conversational_status(self, agent: str) -> str:
        """Return the current conversational label for ``agent`` — one of
        ``"healthy"``, ``"warn"``, ``"degraded"``, ``"inbound_deaf"``, or
        ``"unknown"`` if we've never pinged the agent.
        """
        st = self.status.get(agent)
        if not st:
            return "unknown"
        return st.get("conversationally", "unknown")


# ---------------------------------------------------------------------------
# Scan-loop glue (pure — no I/O)
# ---------------------------------------------------------------------------


def should_ping(
    agent_name: str, current_task: str, idle_seconds: int | None, now: float,
    last_ping_ts: dict[str, float], interval_s: int = 180,
) -> bool:
    """Return True if caduceus should send a greeting to this agent now.

    Policy (issue#168 §4):
      - Every ``interval_s`` seconds per agent (default 3 min).
      - Skip agents that are *actively* working with a fresh task+low idle.
      - Staggered — cadence is per-agent, never a synchronised sweep.

    This helper is pure — the caller supplies ``last_ping_ts`` and
    updates it after posting. Keeping it pure makes the cadence logic
    trivially testable (see ``tests/test_caduceus_greeting.py``).
    """
    if not agent_name:
        return False
    # Skip if agent is visibly working — idle < 30s with a current task
    # means they're typing/running. Don't interrupt. The real inbound-deaf
    # cases show idle=None OR idle much larger, which we still ping.
    if current_task and idle_seconds is not None and idle_seconds < 30:
        return False
    last = last_ping_ts.get(agent_name, 0.0)
    return (now - last) >= interval_s


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "GREETING_FORMAT",
    "GreetingState",
    "InFlightPing",
    "MAX_PING_AGE_S",
    "NONCE_REGEX",
    "format_greeting",
    "new_nonce",
    "parse_pong",
    "should_ping",
]
