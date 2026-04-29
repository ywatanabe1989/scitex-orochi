"""Sleep-loop wrapper for ``daemon-stale-pr``.

Per lead msg#23310: the wrapper is the daemon. Each tick it:
  1. Echoes ``[tick @ <iso-ts>] checking gitea PRs in <repos>...`` to
     stdout (visible if an operator attaches the tmux pane).
  2. Polls each configured repo via :class:`GiteaClient` for open
     PRs + commit-status.
  3. Applies the stale predicate, debounces against last-notified
     state, and DMs the suggested merger via the hub's
     ``POST /api/messages/`` endpoint.
  4. Posts a one-line tick summary
     (``tick=N found=X dispatched=Y``) to ``publish_channel``.
  5. Sleeps ``tick_interval_s``.

For deterministic-only work like FR-N there's no per-tick ``claude
-p`` invocation — that pattern is reserved for FR-M (auditor-haiku),
where rule-judgement *is* the work. The pane visibility requirement
(operator can attach and read what the daemon "is doing") is
satisfied by the stdout echoes here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from scitex_orochi._daemons._stale_pr._check import (
    StalePrFinding,
    findings_from_payload,
    select_stale_for_dm,
)
from scitex_orochi._daemons._stale_pr._state import StalePrState
from scitex_orochi._gitea import GiteaClient

logger = logging.getLogger("orochi.daemon.stale_pr")


@dataclass
class StalePrConfig:
    """Per-deployment config — loaded from ``daemons.yaml``.

    The fields below are the v1 contract. Keep this dataclass small
    and additions backward-compatible (default values) so operators
    can roll the daemon binary forward without touching their yaml.
    """

    gitea_base_url: str
    gitea_token: str
    gitea_owner: str
    repos: list[str]
    repo_to_merger: dict[str, str]
    sender: str = "daemon-stale-pr"
    hub_url: str = ""
    hub_token: str = ""
    publish_channel: str = "#general"  # flips to #daemons once mgr-auth provisions it
    threshold_s: float = 3600.0
    redm_after_s: float = 3600.0
    tick_interval_s: float = 600.0
    log_path: Path = field(
        default_factory=lambda: Path.home()
        / ".scitex"
        / "orochi"
        / "daemon-logs"
        / "stale-pr-daemon.log"
    )

    @classmethod
    def from_env_and_yaml(cls, yaml_path: Path) -> "StalePrConfig":
        """Compose config from env (secrets) + yaml (everything else).

        Secrets stay in env so they don't end up in a versioned
        ``daemons.yaml``: ``OROCHI_GITEA_TOKEN``,
        ``OROCHI_HUB_TOKEN``. The yaml supplies repo lists,
        merger map, thresholds, the channel name.
        """
        import yaml  # type: ignore[import-untyped]

        with yaml_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        block = data.get("daemon-stale-pr") or {}
        return cls(
            gitea_base_url=block.get("gitea_base_url", "https://gitea.scitex.ai"),
            gitea_token=os.environ.get("OROCHI_GITEA_TOKEN", ""),
            gitea_owner=block.get("gitea_owner", "scitex"),
            repos=list(block.get("repos", [])),
            repo_to_merger=dict(block.get("repo_to_merger", {})),
            sender=block.get("sender", "daemon-stale-pr"),
            hub_url=block.get("hub_url", os.environ.get("OROCHI_HUB_URL", "")),
            hub_token=os.environ.get("OROCHI_HUB_TOKEN", ""),
            publish_channel=block.get("publish_channel", "#general"),
            threshold_s=float(block.get("threshold_s", 3600.0)),
            redm_after_s=float(block.get("redm_after_s", 3600.0)),
            tick_interval_s=float(block.get("tick_interval_s", 600.0)),
        )


def _canonical_dm_channel(sender: str, recipient: str) -> str:
    pair = sorted([sender, recipient])
    return f"dm:agent:{pair[0]}|agent:{pair[1]}"


def _post_message(
    *,
    hub_url: str,
    hub_token: str,
    channel: str,
    sender: str,
    text: str,
    timeout: float = 10.0,
) -> bool:
    """POST a message to the hub's ``/api/messages/`` endpoint.

    Mirrors the pattern in
    ``_cli/commands/hungry_signal_cmd.py::_send_dm`` — kept inline
    rather than imported to avoid coupling the daemon to a click
    sub-command's private helpers. If the hungry-signal helper ever
    moves to a shared util, switch over.
    """
    if not (hub_url and hub_token):
        logger.warning("post-message: hub_url/hub_token unset, skipping")
        return False
    endpoint = hub_url.rstrip("/") + f"/api/messages/?token={hub_token}"
    payload = {
        "channel": channel,
        "sender": sender,
        "payload": {"channel": channel, "content": text},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "scitex-orochi-daemon/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 201)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        logger.warning("post-message: %s", exc)
        return False


def _format_dm_text(finding: StalePrFinding, hub_pr_url_base: str = "") -> str:
    age_h = finding.age_seconds / 3600.0
    url_hint = (
        f"\n  {hub_pr_url_base.rstrip('/')}/{finding.repo}/pulls/{finding.number}"
        if hub_pr_url_base
        else ""
    )
    return (
        f"Stale CI-green PR awaiting merge:\n"
        f"  {finding.repo}#{finding.number} — {finding.title}\n"
        f"  author: {finding.author}\n"
        f"  sha: {finding.sha[:12]}\n"
        f"  age: {age_h:.1f}h"
        f"{url_hint}"
    )


def _append_log(log_path: Path, record: dict) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), **record}, default=str) + "\n")
    except OSError as exc:
        logger.warning("append_log: %s", exc)


@dataclass
class TickResult:
    """Outcome of one tick — returned for tests + summary post."""

    found: int
    dispatched: int
    suppressed: int
    errors: list[str] = field(default_factory=list)


async def _fetch_repo_state(
    client: GiteaClient, owner: str, repo: str
) -> tuple[list[Mapping], dict[str, Mapping]]:
    """Pull open PRs + their combined commit-status. One repo's worth."""
    pulls = await client._request(
        "GET", f"/repos/{owner}/{repo}/pulls?state=open"
    )
    pulls = pulls or []
    status_lookup: dict[str, Mapping] = {}
    for pr in pulls:
        sha = pr.get("head", {}).get("sha")
        if not sha:
            continue
        try:
            status = await client._request(
                "GET", f"/repos/{owner}/{repo}/commits/{sha}/status"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch_repo_state: %s/%s sha=%s: %s", owner, repo, sha, exc)
            status = {"state": "unknown"}
        status_lookup[sha] = status or {}
    return pulls, status_lookup


async def run_tick_async(
    cfg: StalePrConfig,
    state: StalePrState,
    *,
    now_ts: float | None = None,
) -> TickResult:
    """One async tick — fetch, classify, debounce, dispatch, log."""
    now = now_ts if now_ts is not None else time.time()
    iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    print(
        f"[tick @ {iso}] checking gitea PRs in {','.join(cfg.repos)}...",
        flush=True,
    )
    all_findings: list[StalePrFinding] = []
    errors: list[str] = []
    client = GiteaClient(cfg.gitea_base_url, cfg.gitea_token)
    try:
        for repo in cfg.repos:
            try:
                pulls, status_lookup = await _fetch_repo_state(
                    client, cfg.gitea_owner, repo
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"fetch failed for {repo}: {exc}"
                logger.warning(msg)
                errors.append(msg)
                continue
            findings = findings_from_payload(
                pulls, status_lookup, repo, threshold_s=cfg.threshold_s, now_ts=now
            )
            all_findings.extend(findings)
    finally:
        await client.close()

    if not state._loaded:
        state.load()
    to_dispatch = select_stale_for_dm(
        all_findings, state, redm_after_s=cfg.redm_after_s, now_ts=now
    )

    dispatched = 0
    for finding in to_dispatch:
        merger = cfg.repo_to_merger.get(finding.repo)
        if not merger:
            errors.append(f"no merger configured for {finding.repo}")
            continue
        channel = _canonical_dm_channel(cfg.sender, merger)
        text = _format_dm_text(finding)
        ok = _post_message(
            hub_url=cfg.hub_url,
            hub_token=cfg.hub_token,
            channel=channel,
            sender=cfg.sender,
            text=text,
        )
        if ok:
            state.record_notified(finding.key, when=now)
            dispatched += 1
            print(
                f"  dispatched DM to {merger} for {finding.key} "
                f"(age {finding.age_seconds / 3600.0:.1f}h)",
                flush=True,
            )
        else:
            errors.append(f"DM failed for {finding.key} -> {merger}")

    suppressed = len(all_findings) - len(to_dispatch)
    summary = f"tick=stale-pr found={len(all_findings)} dispatched={dispatched}"
    if suppressed:
        summary += f" suppressed={suppressed}"
    if errors:
        summary += f" errors={len(errors)}"
    print(f"  {summary}", flush=True)
    _post_message(
        hub_url=cfg.hub_url,
        hub_token=cfg.hub_token,
        channel=cfg.publish_channel,
        sender=cfg.sender,
        text=summary,
    )
    _append_log(
        cfg.log_path,
        {
            "found": len(all_findings),
            "dispatched": dispatched,
            "suppressed": suppressed,
            "errors": errors,
        },
    )
    return TickResult(
        found=len(all_findings),
        dispatched=dispatched,
        suppressed=suppressed,
        errors=errors,
    )


def run_loop(
    cfg: StalePrConfig,
    state: StalePrState,
    *,
    max_ticks: int | None = None,
) -> None:
    """Sleep-loop entry point. Blocks until SIGTERM/SIGINT or max_ticks."""
    print(
        f"daemon-stale-pr: starting (interval={cfg.tick_interval_s}s, "
        f"repos={cfg.repos}, publish={cfg.publish_channel})",
        flush=True,
    )
    n = 0
    while True:
        try:
            asyncio.run(run_tick_async(cfg, state))
        except KeyboardInterrupt:
            print("daemon-stale-pr: interrupted, exiting", flush=True)
            break
        except Exception as exc:  # noqa: BLE001
            # Never let one bad tick kill the daemon — log and sleep on.
            logger.exception("tick raised: %s", exc)
            print(f"  tick error: {exc}", flush=True, file=sys.stderr)
        n += 1
        if max_ticks is not None and n >= max_ticks:
            break
        time.sleep(cfg.tick_interval_s)


__all__ = [
    "StalePrConfig",
    "TickResult",
    "run_tick_async",
    "run_loop",
]
