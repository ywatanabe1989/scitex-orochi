#!/usr/bin/env python3
"""scitex.ai observer-TSV error-rate monitor (#237).

Runs hourly (via orochi-cron or crontab). Reads the per-minute nginx
metrics written by the scitex-cloud observer timer at
``~/proj/scitex-cloud/logs/obs/YYYY-MM-DD.tsv`` and fires an Orochi
bulletin-board post + optional GitHub incident issue when error rates
stay elevated for 3+ consecutive minutes.

Thresholds (from issue #237):
  - nginx_504_1m  > 10  for 3 consecutive minutes
  - nginx_5xx_1m  > 20  for 3 consecutive minutes

Escalation path:
  1. Post to Orochi #general (or OROCHI_OBS_CHANNEL env var).
  2. File a GitHub incident issue on scitex-cloud (with stack dump if
     available) — only once per incident window (tracked via state file).
  3. (todo) scitex notification call — not implemented here; operator
     can configure an upstream alertmanager webhook.

Guardrails:
  - Pure observation + notification. Never deploys, never reverts.
  - Max one Orochi post per hour (state file at ~/.scitex/obs-scan.json).
  - ``--dry-run`` prints what would fire without posting.

Usage::

    python3 observer-tsv-scan.py
    python3 observer-tsv-scan.py --dry-run
    python3 observer-tsv-scan.py --tsv /path/to/file.tsv --window 5
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ── Configuration ────────────────────────────────────────────────────────────

DEFAULT_OBS_ROOT = Path(os.path.expanduser("~/proj/scitex-cloud/logs/obs"))
DEFAULT_STACKS_DIR = DEFAULT_OBS_ROOT / "stacks"
STATE_FILE = Path(os.path.expanduser("~/.scitex/obs-scan.json"))

THRESHOLD_504_1M = 10
THRESHOLD_5XX_1M = 20
CONSEC_MINUTES = 3  # consecutive minutes above threshold to trigger

COOLDOWN_SECONDS = 3600  # one notification per hour

# Orochi hub connection
OROCHI_HOST = os.environ.get("SCITEX_OROCHI_HOST", "http://127.0.0.1:8559")
OROCHI_TOKEN = os.environ.get("SCITEX_OROCHI_TOKEN", "")
OROCHI_CHANNEL = os.environ.get("SCITEX_OROCHI_OBS_CHANNEL", "#general")

# GitHub
GH_REPO = os.environ.get("SCITEX_CLOUD_REPO", "ywatanabe1989/scitex-cloud")

# ── TSV helpers ──────────────────────────────────────────────────────────────


def _find_tsv(obs_root: Path, date: datetime.date | None = None) -> Path | None:
    """Return today's TSV path; fall back to the most recent file if absent."""
    if date is None:
        date = datetime.date.today()
    target = obs_root / f"{date}.tsv"
    if target.exists():
        return target
    # Fall back to most recent file in directory
    tsvs = sorted(obs_root.glob("*.tsv"))
    return tsvs[-1] if tsvs else None


def _parse_nginx_rows(tsv_path: Path) -> list[dict[str, Any]]:
    """Return rows for the _nginx container, parsed into dicts."""
    rows: list[dict[str, Any]] = []
    try:
        with open(tsv_path, encoding="utf-8") as fh:
            header = fh.readline().rstrip("\n").split("\t")
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < len(header):
                    parts += [""] * (len(header) - len(parts))
                row = dict(zip(header, parts))
                if "_nginx" in row.get("container", ""):
                    rows.append(row)
    except OSError:  # stx-allow: fallback (reason: file read failure returns empty list — TSV may not exist yet)
        pass
    return rows


def _to_float(val: str) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):  # stx-allow: fallback (reason: type coercion or format mismatch — missing metric field)
        return 0.0


def _check_consecutive(
    rows: list[dict[str, Any]],
    window: int,
    threshold_504: float,
    threshold_5xx: float,
) -> tuple[bool, list[dict[str, Any]]]:
    """Scan the last ``window * 2`` rows for ``window`` consecutive breaches.

    Returns (triggered, offending_rows).
    """
    # Look at recent rows only (last 30 minutes of data)
    recent = rows[-30:]
    run: list[dict[str, Any]] = []
    for row in recent:
        v504 = _to_float(row.get("nginx_504_1m", ""))
        v5xx = _to_float(row.get("nginx_5xx_1m", ""))
        if v504 > threshold_504 or v5xx > threshold_5xx:
            run.append(row)
            if len(run) >= window:
                return True, run[-window:]
        else:
            run = []
    return False, []


# ── State / rate-limiting ────────────────────────────────────────────────────


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:  # stx-allow: fallback (reason: state file absent or corrupt — treat as fresh)
        return {}


def _save_state(state: dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:  # stx-allow: fallback (reason: state file write failure — alerting continues without persistence)
        pass


def _cooldown_active(state: dict[str, Any]) -> bool:
    last = state.get("last_alert_ts")
    if not last:
        return False
    try:
        delta = datetime.datetime.now().timestamp() - float(last)
        return delta < COOLDOWN_SECONDS
    except Exception:  # stx-allow: fallback (reason: timestamp parse failure — assume cooldown inactive)
        return False


# ── Orochi posting ───────────────────────────────────────────────────────────


def _post_to_orochi(text: str, dry_run: bool) -> bool:
    """POST a message to the Orochi hub via /api/messages/."""
    if dry_run:
        print(f"[dry-run] would post to {OROCHI_CHANNEL}:\n{text}")
        return True
    if not OROCHI_TOKEN:
        print("WARN: SCITEX_OROCHI_TOKEN not set — skipping Orochi post", file=sys.stderr)
        return False
    url = f"{OROCHI_HOST}/api/messages/"
    payload = json.dumps(
        {"channel": OROCHI_CHANNEL, "text": text, "token": OROCHI_TOKEN}
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status < 300
    except urllib.error.URLError as exc:  # stx-allow: fallback (reason: expected failure — Orochi hub may be unreachable during incident)
        print(f"WARN: Orochi post failed: {exc}", file=sys.stderr)
        return False


# ── GitHub issue ─────────────────────────────────────────────────────────────


def _find_stack_dump(stacks_dir: Path) -> str:
    """Return the most recent stack dump text (last 50 lines), or ''."""
    if not stacks_dir.exists():
        return ""
    dumps = sorted(stacks_dir.glob("*.txt")) + sorted(stacks_dir.glob("*.log"))
    if not dumps:
        return ""
    try:
        lines = dumps[-1].read_text(encoding="utf-8", errors="replace").splitlines()
        snippet = "\n".join(lines[-50:])
        return f"**Stack dump** ({dumps[-1].name}):\n```\n{snippet}\n```"
    except OSError:  # stx-allow: fallback (reason: file read failure — stack dump unavailable)
        return ""


def _recent_deploy_hint(scitex_cloud_dir: Path | None = None) -> str:
    """Return a rollback hint if a deploy happened in the last 10 minutes."""
    if scitex_cloud_dir is None:
        scitex_cloud_dir = Path(os.path.expanduser("~/proj/scitex-cloud"))
    if not scitex_cloud_dir.exists():
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", str(scitex_cloud_dir), "log", "--oneline", "-5",
             "--format=%ci %s", "main"],
            capture_output=True, text=True, timeout=10,
        )
        lines = result.stdout.strip().splitlines()
        now = datetime.datetime.now(datetime.timezone.utc)
        for line in lines:
            try:
                parts = line.split(" ", 3)
                ts_str = f"{parts[0]}T{parts[1]}{parts[2]}"
                commit_dt = datetime.datetime.fromisoformat(ts_str)
                if commit_dt.tzinfo is None:
                    commit_dt = commit_dt.replace(tzinfo=datetime.timezone.utc)
                age_min = (now - commit_dt).total_seconds() / 60
                if age_min <= 10:
                    subject = " ".join(parts[3:]) if len(parts) > 3 else line
                    return (
                        f"\n\n⚠️ **Recent deploy detected** (~{int(age_min)} min ago): "
                        f"`{subject.strip()}` — consider rollback if spike is related."
                    )
            except Exception:  # stx-allow: fallback (reason: git log parse failure — skip deploy hint)
                continue
    except Exception:  # stx-allow: fallback (reason: git subprocess failure — deploy hint unavailable)
        pass
    return ""


def _file_incident_issue(
    offending_rows: list[dict[str, Any]],
    tsv_path: Path,
    dry_run: bool,
) -> str | None:
    """File a GitHub issue and return the URL, or None on failure."""
    stack = _find_stack_dump(DEFAULT_STACKS_DIR)
    deploy_hint = _recent_deploy_hint()

    row_table = "| ts_utc | 5xx_1m | 504_1m | 499_1m |\n|---|---|---|---|\n"
    for r in offending_rows:
        row_table += (
            f"| {r.get('ts_utc','')} "
            f"| {r.get('nginx_5xx_1m','')} "
            f"| {r.get('nginx_504_1m','')} "
            f"| {r.get('nginx_499_1m','')} |\n"
        )

    body = (
        f"## Incident: nginx error spike detected\n\n"
        f"**Source**: `{tsv_path.name}` observer TSV\n"
        f"**Triggered**: {CONSEC_MINUTES}+ consecutive minutes above threshold "
        f"(504_1m>{THRESHOLD_504_1M} or 5xx_1m>{THRESHOLD_5XX_1M})\n\n"
        f"### Offending rows\n\n{row_table}"
        f"{deploy_hint}\n\n"
        f"{stack}\n\n"
        f"*Filed automatically by `observer-tsv-scan.py` on NAS.*"
    )
    title = (
        f"incident: nginx error spike {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
    )
    if dry_run:
        print(f"[dry-run] would file issue: {title}")
        return "https://github.com/example/issue/dry-run"
    try:
        result = subprocess.run(
            ["gh", "issue", "create",
             "--repo", GH_REPO,
             "--title", title,
             "--body", body,
             "--label", "incident"],
            capture_output=True, text=True, timeout=30,
        )
        url = result.stdout.strip()
        return url if url.startswith("http") else None
    except Exception as exc:  # stx-allow: fallback (reason: gh CLI failure — incident issue not filed)
        print(f"WARN: gh issue create failed: {exc}", file=sys.stderr)
        return None


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="scitex.ai observer-TSV error monitor")
    parser.add_argument("--tsv", help="Path to TSV file (default: today's)")
    parser.add_argument("--obs-root", default=str(DEFAULT_OBS_ROOT),
                        help="Directory containing YYYY-MM-DD.tsv files")
    parser.add_argument("--window", type=int, default=CONSEC_MINUTES,
                        help="Consecutive minutes threshold (default 3)")
    parser.add_argument("--threshold-504", type=float, default=THRESHOLD_504_1M)
    parser.add_argument("--threshold-5xx", type=float, default=THRESHOLD_5XX_1M)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without posting")
    parser.add_argument("--force", action="store_true",
                        help="Ignore cooldown and always check/alert")
    args = parser.parse_args()

    obs_root = Path(args.obs_root)
    tsv_path = Path(args.tsv) if args.tsv else _find_tsv(obs_root)
    if tsv_path is None or not tsv_path.exists():
        print(f"No TSV file found in {obs_root}", file=sys.stderr)
        return 1

    rows = _parse_nginx_rows(tsv_path)
    if not rows:
        print(f"No _nginx rows in {tsv_path}")
        return 0

    triggered, offending = _check_consecutive(
        rows, args.window, args.threshold_504, args.threshold_5xx
    )

    if not triggered:
        print(f"OK: no sustained error spike in {tsv_path.name} ({len(rows)} nginx rows checked)")
        return 0

    # Spike detected
    state = _load_state()
    if not args.force and _cooldown_active(state):
        print("Spike detected but cooldown active — skipping notification")
        return 0

    # Format alert message
    worst_5xx = max(_to_float(r.get("nginx_5xx_1m", "")) for r in offending)
    worst_504 = max(_to_float(r.get("nginx_504_1m", "")) for r in offending)
    deploy_hint = _recent_deploy_hint()

    msg = (
        f"🚨 **scitex.ai nginx error spike** ({tsv_path.name})\n"
        f"  • {args.window}+ consecutive minutes above threshold\n"
        f"  • Peak 5xx_1m: **{worst_5xx:.0f}** (threshold {args.threshold_5xx})\n"
        f"  • Peak 504_1m: **{worst_504:.0f}** (threshold {args.threshold_504})\n"
        f"  • Window: {offending[0].get('ts_utc','')} → {offending[-1].get('ts_utc','')}"
    )
    if deploy_hint:
        msg += deploy_hint

    _post_to_orochi(msg, dry_run=args.dry_run)

    # File GitHub incident issue
    issue_url = _file_incident_issue(offending, tsv_path, dry_run=args.dry_run)
    if issue_url:
        followup = f"📋 Incident filed: {issue_url}"
        _post_to_orochi(followup, dry_run=args.dry_run)

    # Update rate-limit state
    if not args.dry_run:
        state["last_alert_ts"] = datetime.datetime.now().timestamp()
        state["last_tsv"] = str(tsv_path)
        state["last_offending_window"] = [r.get("ts_utc", "") for r in offending]
        _save_state(state)

    print(f"ALERT fired: spike in {tsv_path.name}, {args.window} consecutive minutes")
    return 2  # non-zero → cron runner knows an alert fired


if __name__ == "__main__":
    sys.exit(main())
