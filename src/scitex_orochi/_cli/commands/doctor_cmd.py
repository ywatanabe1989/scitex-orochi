"""CLI command: scitex-orochi doctor -- diagnose the full stack."""

from __future__ import annotations

import json
import subprocess
import sys

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER


def _check(label: str, ok: bool, detail: str = "") -> dict:
    """Print a check result and return it as dict."""
    tag = "[OK]" if ok else "[!!]"
    line = f"  {tag}  {label}"
    if detail:
        line += f": {detail}"
    click.echo(line)
    return {"check": label, "ok": ok, "detail": detail}


@click.command(
    "doctor",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi doctor\n"
    + "  scitex-orochi doctor --json\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def doctor_cmd(ctx: click.Context, as_json: bool) -> None:
    """Diagnose connectivity, services, and configuration."""
    from importlib.metadata import version as pkg_version

    from scitex_orochi._config import (
        CORS_ORIGINS,
        DASHBOARD_WS_UPSTREAM,
        DB_PATH,
        GITEA_TOKEN,
        GITEA_URL,
        OROCHI_TOKEN,
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_BRIDGE_ENABLED,
    )

    host = ctx.obj["host"]
    port = ctx.obj["port"]
    results: list[dict] = []

    # Version
    try:
        ver = pkg_version("scitex-orochi")
    except Exception:
        ver = "dev"

    if not as_json:
        click.echo(f"\nscitex-orochi v{ver}\n")

    # 1. Server connectivity (WebSocket)
    try:
        import asyncio

        from scitex_orochi._cli._helpers import make_client

        async def _probe() -> dict:
            async with make_client(host, port) as client:
                return await client.who()

        agents = asyncio.run(_probe())
        results.append(
            _check("Server", True, f"{host}:{port}")
            if not as_json
            else {"check": "Server", "ok": True, "detail": f"{host}:{port}"}
        )
    except Exception as exc:
        results.append({"check": "Server", "ok": False, "detail": str(exc)})
        if not as_json:
            _check("Server", False, f"{host}:{port} -- {exc}")
        agents = {}

    # 2. Agents online
    agent_count = len(agents)
    ok = agent_count > 0
    results.append({"check": "Agents online", "ok": ok, "detail": str(agent_count)})
    if not as_json:
        _check("Agents online", ok, str(agent_count))

    # 3. Channels
    ch_set: set[str] = set()
    for info in agents.values():
        if isinstance(info, dict):
            ch_set.update(info.get("channels", []))
    ch_str = ", ".join(sorted(ch_set)) if ch_set else "none"
    results.append({"check": "Channels", "ok": bool(ch_set), "detail": ch_str})
    if not as_json:
        _check("Channels", bool(ch_set), ch_str)

    # 4. Auth token
    has_token = bool(OROCHI_TOKEN)
    results.append(
        {
            "check": "Auth token",
            "ok": has_token,
            "detail": "configured" if has_token else "not set (open access)",
        }
    )
    if not as_json:
        _check(
            "Auth token",
            has_token,
            "configured" if has_token else "not set (open access)",
        )

    # 5. Database path
    from pathlib import Path

    db = Path(DB_PATH)
    db_exists = db.exists()
    db_detail = f"{DB_PATH}"
    if db_exists:
        size_mb = db.stat().st_size / (1024 * 1024)
        db_detail += f" ({size_mb:.1f} MB)"
    results.append({"check": "Database", "ok": db_exists, "detail": db_detail})
    if not as_json:
        _check("Database", db_exists, db_detail)

    # 6. Telegram bridge
    tg_detail = "enabled" if TELEGRAM_BRIDGE_ENABLED else "disabled"
    if TELEGRAM_BRIDGE_ENABLED and not TELEGRAM_BOT_TOKEN:
        tg_detail = "enabled but TELEGRAM_BOT_TOKEN not set"
    results.append({"check": "Telegram bridge", "ok": True, "detail": tg_detail})
    if not as_json:
        _check(
            "Telegram bridge",
            not (TELEGRAM_BRIDGE_ENABLED and not TELEGRAM_BOT_TOKEN),
            tg_detail,
        )

    # 7. Gitea
    gitea_ok = bool(GITEA_TOKEN) or GITEA_URL == ""
    gitea_detail = GITEA_URL if GITEA_URL else "not configured"
    if GITEA_URL and not GITEA_TOKEN:
        gitea_detail += " (no token)"
    results.append({"check": "Gitea", "ok": gitea_ok, "detail": gitea_detail})
    if not as_json:
        _check("Gitea", gitea_ok, gitea_detail)

    # 8. CORS origins
    if CORS_ORIGINS:
        results.append({"check": "CORS origins", "ok": True, "detail": CORS_ORIGINS})
        if not as_json:
            _check("CORS origins", True, CORS_ORIGINS)

    # 9. WS upstream (dev sync)
    if DASHBOARD_WS_UPSTREAM:
        results.append(
            {"check": "WS upstream", "ok": True, "detail": DASHBOARD_WS_UPSTREAM}
        )
        if not as_json:
            _check("WS upstream", True, DASHBOARD_WS_UPSTREAM)

    # 10. Docker containers
    for env, container in [
        ("stable", "orochi-server-stable"),
        ("dev", "orochi-server-dev"),
    ]:
        proc = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"name={container}",
                "--format",
                "{{.Status}}",
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            results.append(
                {
                    "check": f"Docker {env}",
                    "ok": False,
                    "detail": "docker not available",
                }
            )
            if not as_json:
                _check(f"Docker {env}", False, "docker not available")
        elif proc.stdout.strip():
            results.append(
                {"check": f"Docker {env}", "ok": True, "detail": proc.stdout.strip()}
            )
            if not as_json:
                _check(f"Docker {env}", True, proc.stdout.strip())
        else:
            results.append(
                {"check": f"Docker {env}", "ok": False, "detail": "not running"}
            )
            if not as_json:
                _check(f"Docker {env}", False, "not running")

    # Summary
    errors = sum(1 for r in results if not r["ok"])
    ok_count = sum(1 for r in results if r["ok"])

    if as_json:
        click.echo(
            json.dumps(
                {
                    "version": ver,
                    "checks": results,
                    "ok": ok_count,
                    "errors": errors,
                },
                indent=2,
            )
        )
    else:
        click.echo(f"\n{ok_count} ok, {errors} issues")

    if errors > 0:
        sys.exit(1)
