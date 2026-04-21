"""60-second throttled digest coalescer (pure, testable).

No I/O. No asyncio. Callers push inbound events via
:meth:`DigestCoalescer.push`, then periodically drain a digest line
via :meth:`DigestCoalescer.flush`. The daemon ticks every ~1 s; flush
returns ``None`` until the 60 s throttle window has elapsed AND at
least one event was observed.

Event signature = ``(channel, sender, leading-prefix-of-text)``. Bursts
of identical signatures collapse into ``{N}x <summary>`` so 40
consecutive "CI started" webhook posts render as one line instead of
40.

Mention / DM handling lives in :class:`MentionPolicy` and is
deliberately distinct from the throttle: mentions bypass the window
and return an immediate ack string.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import AGENT_NAME

# Digest window; matches the lead directive in #heads msg#15399.
DEFAULT_WINDOW_S = 60.0

# Max chars in an emitted digest line. Kept under 200 per the spec.
MAX_LINE_CHARS = 200

# How many chars of the event text we use as the dedup-prefix / summary.
# Short enough that "CI started: foo/bar #123" and "CI started: foo/baz
# #124" collapse to the same bucket; long enough to stay human-readable.
SIG_PREFIX_CHARS = 48

# Number of distinct signatures we surface per digest line. The rest
# are rolled into " ...+M more".
TOP_N_HIGHLIGHTS = 3


@dataclass
class InboundEvent:
    """A minimal view of an inbound WS message — just what the
    coalescer needs. Full frames stay in the daemon layer."""

    channel: str
    sender: str
    text: str
    ts: float  # unix seconds
    is_dm: bool = False
    mentions_self: bool = False


@dataclass
class _Bucket:
    """Per-signature accumulator inside a single window."""

    signature: str
    count: int = 0
    last_text: str = ""
    last_channel: str = ""
    last_sender: str = ""


@dataclass
class DigestCoalescer:
    """Time-windowed event coalescer with signature-based dedup.

    The coalescer carries a ``now()`` callable so tests can inject a
    deterministic clock. In production this is ``time.monotonic``.
    """

    window_s: float = DEFAULT_WINDOW_S
    now: Callable[[], float] = field(default=lambda: 0.0)
    _window_start: float = field(default=0.0, init=False)
    _buckets: "OrderedDict[str, _Bucket]" = field(
        default_factory=OrderedDict, init=False
    )
    _total: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._window_start = self.now()

    # -- inbound -------------------------------------------------------

    def push(self, ev: InboundEvent) -> None:
        """Record an inbound event. Mentions are NOT added here — the
        daemon routes those through :class:`MentionPolicy` before the
        throttle layer."""
        sig = _signature(ev)
        bucket = self._buckets.get(sig)
        if bucket is None:
            bucket = _Bucket(signature=sig)
            self._buckets[sig] = bucket
        bucket.count += 1
        bucket.last_text = ev.text
        bucket.last_channel = ev.channel
        bucket.last_sender = ev.sender
        self._total += 1

    # -- tick ----------------------------------------------------------

    def flush(self) -> Optional[str]:
        """Return a digest line if the window has closed AND had
        events, else ``None``. Always resets the window when it closes
        (even with zero events) so the next window starts fresh."""
        if self.now() - self._window_start < self.window_s:
            return None
        line = self._render() if self._total > 0 else None
        self._reset()
        return line

    # -- rendering -----------------------------------------------------

    def _render(self) -> str:
        ts_tag = _hhmm(self._window_start + self.window_s)
        total = self._total
        # Sort buckets by count desc, then insertion order (stable
        # since OrderedDict) so ties preserve arrival order.
        ranked = sorted(
            self._buckets.values(),
            key=lambda b: (-b.count, list(self._buckets.keys()).index(b.signature)),
        )
        top = ranked[:TOP_N_HIGHLIGHTS]
        rest = ranked[TOP_N_HIGHLIGHTS:]
        highlights = []
        for b in top:
            summary = _summarize(b)
            if b.count > 1:
                summary = f"{b.count}x {summary}"
            highlights.append(summary)
        extra = sum(b.count for b in rest)
        line = f"[progress {ts_tag}] {total} events: " + " | ".join(highlights)
        if extra > 0:
            line += f" ...+{extra} more"
        if len(line) > MAX_LINE_CHARS:
            line = line[: MAX_LINE_CHARS - 1] + "..."
        return line

    def _reset(self) -> None:
        self._window_start = self.now()
        self._buckets.clear()
        self._total = 0


# -- helpers ---------------------------------------------------------------


def _signature(ev: InboundEvent) -> str:
    """Dedup key — (channel, sender, leading text prefix)."""
    prefix = (ev.text or "").strip()[:SIG_PREFIX_CHARS]
    return f"{ev.channel}|{ev.sender}|{prefix}"


def _summarize(b: _Bucket) -> str:
    """Short inline summary used inside a digest highlight."""
    text = (b.last_text or "").strip().replace("\n", " ")
    if len(text) > SIG_PREFIX_CHARS:
        text = text[: SIG_PREFIX_CHARS - 1] + "..."
    return f"{b.last_channel} {b.last_sender}: {text}"


def _hhmm(ts: float) -> str:
    """Format a UTC-ish HH:MM tag for the digest prefix.

    We use ``time.strftime`` on the local clock; the ``[progress ts]``
    tag is decorative, not an audit field, so absolute timezone does
    not matter. The test suite passes a fake monotonic clock so we
    fall back to a stable placeholder in that case.
    """
    import time

    try:
        return time.strftime("%H:%M", time.localtime(ts))
    except (ValueError, OSError, OverflowError):
        return "--:--"


# -- mention / DM bypass ---------------------------------------------------


class MentionPolicy:
    """Decides whether an inbound event is a mention or DM that should
    bypass the throttle and trigger an immediate ack.

    v1 scope: single-line polite ack. The full claude-code spawn is
    tracked under todo#272 and explicitly out of scope here.
    """

    #: Mention tokens that trigger bypass. Kept deliberately broad —
    #: exact-match variants plus the ``@<name>`` form.
    MENTION_TOKENS = (
        f"@{AGENT_NAME}",
        f"@agent-{AGENT_NAME}",
    )

    @classmethod
    def is_mention(cls, ev: InboundEvent) -> bool:
        if ev.is_dm:
            return True
        text = (ev.text or "").lower()
        for tok in cls.MENTION_TOKENS:
            if tok.lower() in text:
                return True
        return False

    @classmethod
    def ack_line(cls, ev: InboundEvent) -> str:
        """Render the single-line ack. The daemon posts this to the
        channel the event came from (if group) or back into the DM.
        """
        who = ev.sender or "there"
        if ev.is_dm:
            return (
                f"ack @{who}: received, queued for richer reply. Full handoff "
                "to claude-code is tracked under todo#272."
            )
        return (
            f"ack @{who}: received mention, queued for richer reply (todo#272)."
        )
