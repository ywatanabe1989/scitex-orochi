"""Bypass-case tests for the .env file redaction layer surfaced by the
2026-04-27 audit (`mgmt/REVIEWER_COMMENTS_v02.md` §1).

The previous heuristic (`isalnum()` plus substring `KEY` match) failed
on the most common production secret shapes: quoted values, DSN/URL
userinfo, base64, multi-line PEM, and key suffixes the reviewer flagged
(``MONKEY`` matched; ``DSN``/``URL``/``WEBHOOK`` did not).

These tests pin the producer-side ``_redact_env_line`` /
``_redact_env_text`` and the hub-side ``redact_secrets`` so any
regression that re-opens the bypasses fails CI.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load the producer-side redaction module from the agent script tree
# without importing the whole scitex_orochi package — the test should
# exercise the redaction unit in isolation.
_FILES_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "client"
    / "_collect_agent_metadata"
    / "_files.py"
)
_spec = importlib.util.spec_from_file_location(
    "_collect_agent_metadata_files", _FILES_PATH
)
assert _spec and _spec.loader, f"could not load {_FILES_PATH}"
_files = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _files
_spec.loader.exec_module(_files)  # type: ignore[union-attr]
_redact_env_line = _files._redact_env_line
_redact_env_text = _files._redact_env_text


# Each pair: (input_line, must_NOT_contain). The original secret value
# must not appear in the redacted output. We deliberately avoid
# pinning the exact replacement so the redaction strategy can evolve.
_BYPASS_LINE_CASES: list[tuple[str, str]] = [
    # 1. DSN / URL userinfo — the headline audit finding.
    (
        "DATABASE_URL=postgres://orochi_user:hunter2@db.example.com:5432/orochi",
        "hunter2",
    ),
    (
        "REDIS_URL=redis://:r3d1sP4ss@redis.example.com:6379/0",
        "r3d1sP4ss",
    ),
    (
        "SENTRY_DSN=https://abcdef0123456789@o123.ingest.sentry.io/42",
        "abcdef0123456789",
    ),
    (
        "AMQP_URL=amqp://rabbit:bunny@queue.example.com//",
        "bunny",
    ),
    (
        "MONGO_URI=mongodb+srv://admin:l1mbo@cluster.mongodb.net/db",
        "l1mbo",
    ),
    # 2. Quoted values — the previous isalnum() check failed because of
    # the leading quote character.
    ('API_TOKEN="aaaaaaaaaaaaaaaaaaaaaaaa"', "aaaaaaaaaaaaaaaaaaaaaaaa"),
    ("API_TOKEN='bbbbbbbbbbbbbbbbbbbbbbbb'", "bbbbbbbbbbbbbbbbbbbbbbbb"),
    # 3. Base64 with + / = (previous alnum-only heuristic missed these).
    (
        "JWT_SIGNING_SECRET=Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Cg==",
        "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Cg==",
    ),
    (
        "AWS_SESSION_TOKEN=AQoDYXdzEPT//////////wEXAMPLEtc",
        "AQoDYXdzEPT",
    ),
    # 4. Reviewer-flagged key suffixes that previous substring rule missed.
    ("SLACK_WEBHOOK=https://hooks.slack.com/services/T0/B0/abc123", "abc123"),
    (
        "POSTGRES_CONNECTION_STRING=host=db user=u password=p123 sslmode=require",
        "p123",
    ),
    (
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
        "AKIAIOSFODNN7EXAMPLE",
    ),
    # 5. Vendored prefixes.
    ("ANTHROPIC=sk-ant-abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz"),
    ("OPENAI=sk-abcdefghijklmnopqrstuvwxyz0123", "abcdefghijklmnopqrstuvwxyz0123"),
    ("GH=ghp_abcdefghijklmnopqrstuvwxyz0123", "ghp_abcdefghijklmnopqrstuvwxyz0123"),
]


@pytest.mark.parametrize("line,must_not_contain", _BYPASS_LINE_CASES)
def test_redact_env_line_bypass_cases(line: str, must_not_contain: str) -> None:
    out = _redact_env_line(line)
    assert must_not_contain not in out, (
        f"redaction bypass: input={line!r} → output={out!r} still contains "
        f"{must_not_contain!r}"
    )


def test_redact_env_line_does_not_over_redact_innocuous_keys() -> None:
    # MONKEY / KEYBASE / LOCALE_KEYBOARD must NOT match the sensitive
    # suffix list; values are short and not high-entropy so they should
    # pass through unchanged.
    for line in (
        "MONKEY=banana",
        "KEYBASE_USER=alice",
        "LOCALE_KEYBOARD=us",
        "PROJECT_NAME=orochi",
        "DEBUG=true",
        "PORT=8559",
    ):
        out = _redact_env_line(line)
        assert out == line, f"over-redacted innocuous line: {line!r} → {out!r}"


def test_redact_env_text_strips_pem_blocks() -> None:
    pem = (
        "OK_KEY=foo\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
        "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy\n"
        "-----END RSA PRIVATE KEY-----\n"
        "OTHER=visible\n"
    )
    out = _redact_env_text(pem)
    assert "MIIEpAIBA" not in out
    assert "yyyyyyy" not in out
    assert "BEGIN (REDACTED)" in out
    assert "END (REDACTED)" in out
    assert "OTHER=visible" in out


def test_redact_env_text_redacts_continuation_lines() -> None:
    # A continuation (no `=`) sitting outside a PEM block could be a
    # heredoc body or a JSON value tail. We can't tell, so redact.
    body = 'SAFE_KEY=value\n{"something": "in_json_continuation_value_that_is_long"}\n'
    out = _redact_env_text(body)
    assert "in_json_continuation_value_that_is_long" not in out


# ---------------------------------------------------------------------------
# Hub-side mirror: redact_secrets must also catch DSN userinfo so that
# even if the producer regresses, the dashboard does not render the
# secret.
# ---------------------------------------------------------------------------
def test_hub_redact_secrets_masks_dsn_userinfo() -> None:
    """Mirror of the producer-side DSN test on the hub-side
    `redact_secrets`. Skipped automatically when Django settings aren't
    configured (this test pack is the producer-side suite; the
    hub-side suite is run via `python manage.py test`)."""
    import os

    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        pytest.skip(
            "hub-side test requires DJANGO_SETTINGS_MODULE; covered by "
            "hub/tests/views/api/test_agent_detail.py instead"
        )
    pytest.importorskip("django")
    from hub.views.agent_detail import redact_secrets  # noqa: WPS433

    cases = [
        ("postgres://user:hunter2@db/orochi", "hunter2"),
        ("redis://:r3d1sP4ss@redis:6379", "r3d1sP4ss"),
        ("https://user:pw@example.com/path", "pw"),
        ("mongodb+srv://admin:l1mbo@cluster/db", "l1mbo"),
    ]
    for raw, secret in cases:
        out = redact_secrets(raw)
        assert secret not in out, (
            f"hub-side redact_secrets bypass: {raw!r} → {out!r} still "
            f"contains {secret!r}"
        )
