"""WebSocket subscriber loop for ``daemon-auditor-haiku`` (Stage 1).

Connects via :class:`OrochiClient`, subscribes to the configured
fleet channels, and for each inbound message:

  1. Skip if ``sender == self`` (self-exclusion — never audit own
     audit posts; would loop forever).
  2. Run :func:`audit_message`.
  3. Post one verdict line to ``publish_channel`` (Stage 1: that's
     ``#audit-shadow``; falls back to ``#general`` until provisioned).
  4. Continue.

This is intentionally a long-lived process, *not* fresh-per-tick.
Lead msg#23300 said "fresh process per message" but lead msg#23310
clarified that fresh-per-message is the *judgement* path (each
``claude -p`` invocation), not the subscriber. The subscriber is
the wrapper. For Stage 1 there's no ``claude -p`` (regex only), so
the wrapper-as-subscriber is enough; Stage 1.5 will add a fresh
subprocess spawn inside the audit pipeline when Haiku is wired.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from scitex_orochi._client import OrochiClient
from scitex_orochi._daemons._auditor_haiku._audit import (
    AuditOutcome,
    audit_message,
    render_shadow_line,
)
from scitex_orochi._daemons._auditor_haiku._rules import AuditVerdict, Rule

logger = logging.getLogger("orochi.daemon.auditor_haiku")


@dataclass
class AuditorConfig:
    """Per-deployment config for ``daemon-auditor-haiku``."""

    agent_name: str = "daemon-auditor-haiku"
    hub_host: str = ""
    hub_port: int = 8559
    ws_path: str = "/ws/agent/"
    token: str = ""

    # Channels we subscribe to. Stage 1 is conservative: just the
    # always-on fleet channels. ``#proj-*`` / ``#c-*`` wildcards are
    # not in the v1 protocol; the operator can extend this list
    # explicitly per deployment until the hub supports patterns.
    subscribe_channels: tuple[str, ...] = (
        "#general",
        "#heads",
        "#ywatanabe",
    )

    # Where verdict lines go. Stage 1: ``#audit-shadow``.
    publish_channel: str = "#audit-shadow"

    # Verbosity — emit a line for PASS verdicts as well as FAIL.
    # Lead msg#23300 wanted "log-only ⭕️/❌" so PASS lines exist
    # for soak review. Operator can flip to FAIL-only after Stage 1.
    emit_pass: bool = True

    # When set, only post FAIL lines (overrides emit_pass for noise control).
    fail_only: bool = False

    # Custom rule set; default :func:`default_rules` if None.
    rules: tuple[Rule, ...] | None = None

    @classmethod
    def from_env(cls) -> "AuditorConfig":
        """Compose config from env (the wrapper is launched from a
        sac-managed yaml that sets these)."""
        return cls(
            agent_name=os.environ.get("CLAUDE_AGENT_ID", "daemon-auditor-haiku"),
            hub_host=os.environ.get("OROCHI_HUB_HOST", ""),
            hub_port=int(os.environ.get("OROCHI_HUB_PORT", "8559")),
            ws_path=os.environ.get("OROCHI_HUB_WS_PATH", "/ws/agent/"),
            token=os.environ.get("OROCHI_HUB_TOKEN", ""),
            subscribe_channels=tuple(
                ch.strip()
                for ch in os.environ.get(
                    "AUDITOR_SUBSCRIBE_CHANNELS",
                    "#general,#heads,#ywatanabe",
                ).split(",")
                if ch.strip()
            ),
            publish_channel=os.environ.get(
                "AUDITOR_PUBLISH_CHANNEL", "#audit-shadow"
            ),
            emit_pass=os.environ.get("AUDITOR_EMIT_PASS", "1") not in ("0", "false"),
            fail_only=os.environ.get("AUDITOR_FAIL_ONLY", "0") in ("1", "true"),
        )


@dataclass
class AuditCounters:
    """Cheap in-process counters for the periodic summary line."""

    seen: int = 0
    self_excluded: int = 0
    failed: int = 0
    passed: int = 0


def _should_post(outcome: AuditOutcome, cfg: AuditorConfig) -> bool:
    if cfg.fail_only and outcome.verdict != AuditVerdict.FAIL:
        return False
    if not cfg.emit_pass and outcome.verdict != AuditVerdict.FAIL:
        return False
    return True


async def _process_one_message(
    msg,
    *,
    cfg: AuditorConfig,
    client: OrochiClient,
    counters: AuditCounters,
) -> None:
    """Audit a single inbound message and (maybe) post the verdict."""
    counters.seen += 1
    sender = getattr(msg, "sender", "") or ""
    if sender == cfg.agent_name:
        counters.self_excluded += 1
        return

    payload = getattr(msg, "payload", {}) or {}
    chat_id = payload.get("channel", "") or ""
    text = payload.get("content", "") or ""
    msg_id = payload.get("metadata", {}).get("msg_id", "?") if isinstance(
        payload.get("metadata"), dict
    ) else "?"

    outcome = audit_message(text, rules=cfg.rules)
    if outcome.verdict == AuditVerdict.FAIL:
        counters.failed += 1
    else:
        counters.passed += 1
    if not _should_post(outcome, cfg):
        return
    line = render_shadow_line(
        outcome=outcome,
        chat_id=chat_id,
        msg_id=msg_id,
        user=sender,
        text=text,
    )
    try:
        await client.send(cfg.publish_channel, line)
    except Exception as exc:  # noqa: BLE001
        logger.warning("auditor: post to %s failed: %s", cfg.publish_channel, exc)


async def run(cfg: AuditorConfig) -> AuditCounters:
    """Connect, subscribe, listen, audit. Returns counters when the
    connection closes (caller may choose to reconnect)."""
    counters = AuditCounters()
    async with OrochiClient(
        cfg.agent_name,
        host=cfg.hub_host or None,
        port=cfg.hub_port,
        channels=list(cfg.subscribe_channels),
        token=cfg.token or None,
        role="daemon",
        ws_path=cfg.ws_path,
    ) as client:
        print(
            f"daemon-auditor-haiku: connected as {cfg.agent_name}, "
            f"subscribed to {','.join(cfg.subscribe_channels)}, "
            f"publishing to {cfg.publish_channel}",
            flush=True,
        )
        async for msg in client.listen():
            await _process_one_message(
                msg, cfg=cfg, client=client, counters=counters
            )
    return counters


__all__ = [
    "AuditorConfig",
    "AuditCounters",
    "_process_one_message",
    "_should_post",
    "run",
]
