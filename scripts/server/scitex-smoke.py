#!/usr/bin/env python3
"""scitex.ai post-deploy Playwright smoke test (#237 Part 2).

Runs headless Playwright checks against https://scitex.ai after a main-branch
deploy.  Posts PASS/FAIL to the Orochi bulletin board and optionally saves
screenshots to a timestamped directory.

Checks:
  1. HTTP 200 on /, /landing/, /healthz/, /apps/home/
  2. Visitor auto-login: / eventually shows the home page (not a crash/500)
  3. One content page renders (tries /apps/scholar/, /apps/writer/, /plt/)
  4. No Django debug error pages (yellow 500 / middleware tracebacks)

Usage::

    python3 scitex-smoke.py
    python3 scitex-smoke.py --dry-run      # print report, skip Orochi post
    python3 scitex-smoke.py --base-url https://scitex.ai --screenshot-dir /tmp/smoke

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
    2 — Playwright or network error prevented any checks

References:
    scitex-orochi#237 Part 2
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://scitex.ai"
OROCHI_HOST = os.environ.get("SCITEX_OROCHI_HOST", "http://127.0.0.1:8559")
OROCHI_TOKEN = os.environ.get("SCITEX_OROCHI_TOKEN", "")
OROCHI_CHANNEL = os.environ.get("SCITEX_OROCHI_OBS_CHANNEL", "#general")

# Endpoints that must return 2xx
REQUIRED_PAGES: list[tuple[str, str]] = [
    ("/", "home"),
    ("/landing/", "landing"),
    ("/healthz/", "healthz"),
    ("/apps/home/", "apps-home"),
]

# Content pages — at least one must render (not crash)
CONTENT_PAGES: list[tuple[str, str]] = [
    ("/apps/scholar/", "scholar"),
    ("/apps/writer/", "writer"),
    ("/plt/", "plt"),
]

# Phrases that indicate a Django debug error page or server crash.
# These must be specific enough to avoid false positives — for example
# "middleware" alone matches csrfmiddlewaretoken in every Django form.
ERROR_SIGNALS = [
    "Django tried these URL patterns",
    "Server Error (500)",
    "Application error",
    "Traceback (most recent call last)",
    "<div id=\"traceback\">",
    "DisallowedHost",
    "OperationalError at",
    "ProgrammingError at",
    "IntegrityError at",
    "ImproperlyConfigured",
]

TIMEOUT_MS = 30_000


# ── Playwright helpers ────────────────────────────────────────────────────────


def _check_page(
    page: Any,
    url: str,
    label: str,
    screenshot_dir: Path | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"label": label, "url": url, "ok": False, "error": ""}
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        status = resp.status if resp else None
        content = page.content()

        # Check for error signals in page content
        for sig in ERROR_SIGNALS:
            if sig.lower() in content.lower():
                result["error"] = f"error signal found: {sig!r}"
                if screenshot_dir:
                    _save_screenshot(page, screenshot_dir, label, "fail")
                return result

        if status and status < 400:
            result["ok"] = True
            result["status"] = status
            if screenshot_dir:
                _save_screenshot(page, screenshot_dir, label, "pass")
        else:
            result["error"] = f"HTTP {status}"
            if screenshot_dir:
                _save_screenshot(page, screenshot_dir, label, "fail")
    except Exception as exc:  # stx-allow: fallback (reason: page load failure — mark check failed)
        result["error"] = str(exc)[:200]
        try:
            if screenshot_dir:
                _save_screenshot(page, screenshot_dir, label, "error")
        except Exception:  # stx-allow: fallback (reason: screenshot failure — ignore)
            pass
    return result


def _save_screenshot(page: Any, screenshot_dir: Path, label: str, status: str) -> None:
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    fname = screenshot_dir / f"{label}-{status}.png"
    try:
        page.screenshot(path=str(fname))
    except Exception:  # stx-allow: fallback (reason: screenshot save failure — continue)
        pass


# ── Orochi posting ────────────────────────────────────────────────────────────


def _post_to_orochi(text: str, dry_run: bool) -> bool:
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
    except urllib.error.URLError as exc:  # stx-allow: fallback (reason: Orochi hub unreachable during smoke run)
        print(f"WARN: Orochi post failed: {exc}", file=sys.stderr)
        return False


# ── Report formatting ─────────────────────────────────────────────────────────


def _format_report(
    results: list[dict[str, Any]],
    content_ok: bool,
    base_url: str,
    elapsed_s: float,
    screenshot_dir: Path | None,
) -> tuple[str, bool]:
    passed = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    all_ok = len(failed) == 0 and content_ok

    status_icon = "✅" if all_ok else "🚨"
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"{status_icon} **scitex.ai smoke test** — {'PASS' if all_ok else 'FAIL'} ({ts})",
        f"  • Target: `{base_url}`",
        f"  • {len(passed)}/{len(results)} required pages OK  |  content render: {'✅' if content_ok else '❌'}",
        f"  • Elapsed: {elapsed_s:.1f}s",
    ]
    if failed:
        lines.append("  • Failed checks:")
        for r in failed:
            lines.append(f"    – `{r['label']}` ({r['url']}): {r['error']}")
    if not content_ok:
        lines.append("  • Content page: all tried pages returned errors")
    if screenshot_dir and screenshot_dir.exists():
        lines.append(f"  • Screenshots: `{screenshot_dir}`")
    return "\n".join(lines), all_ok


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="scitex.ai Playwright smoke test (#237)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report without posting to Orochi")
    parser.add_argument("--screenshot-dir", default="",
                        help="Directory for failure screenshots (default: temp)")
    parser.add_argument("--no-screenshots", action="store_true",
                        help="Disable screenshot capture")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    screenshot_dir: Path | None = None
    if not args.no_screenshots:
        if args.screenshot_dir:
            screenshot_dir = Path(args.screenshot_dir)
        else:
            ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            screenshot_dir = Path(f"/tmp/scitex-smoke-{ts}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # stx-allow: fallback (reason: playwright not installed — exit 2)
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 2

    start = datetime.datetime.utcnow()
    results: list[dict[str, Any]] = []
    content_ok = False

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
                    "SciTeXSmokeBot/1.0"
                ),
                ignore_https_errors=False,
            )
            page = context.new_page()

            # Required pages
            for path, label in REQUIRED_PAGES:
                r = _check_page(page, base_url + path, label, screenshot_dir)
                results.append(r)
                print(f"{'PASS' if r['ok'] else 'FAIL'} {label}: {r.get('status','?')} {r.get('error','')}")

            # Content pages — at least one must work
            for path, label in CONTENT_PAGES:
                r = _check_page(page, base_url + path, label, screenshot_dir)
                print(f"{'PASS' if r['ok'] else 'FAIL'} {label}: {r.get('status','?')} {r.get('error','')}")
                if r["ok"]:
                    content_ok = True
                    break

            browser.close()

    except Exception as exc:  # stx-allow: fallback (reason: Playwright launch failure — report and exit 2)
        print(f"ERROR: Playwright failed: {exc}", file=sys.stderr)
        _post_to_orochi(
            f"🚨 **scitex.ai smoke test ERROR** — Playwright failed to launch: {exc}",
            dry_run=args.dry_run,
        )
        return 2

    elapsed_s = (datetime.datetime.utcnow() - start).total_seconds()
    report, all_ok = _format_report(results, content_ok, base_url, elapsed_s, screenshot_dir)
    print()
    print(report)
    _post_to_orochi(report, dry_run=args.dry_run)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
