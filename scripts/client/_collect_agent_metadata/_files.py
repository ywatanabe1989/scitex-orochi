"""CLAUDE.md / .mcp.json discovery + read for the agent-detail viewers (todo#460)."""

from __future__ import annotations

import json
import re
from pathlib import Path


def collect_orochi_skills_loaded(workspace: str) -> list[str]:
    """Scan the workspace CLAUDE.md for ```skills fences and return the names."""
    orochi_skills_loaded: list[str] = []
    try:
        cmd = Path(workspace) / "CLAUDE.md"
        if cmd.is_file():
            text = cmd.read_text()
            for block in re.findall(r"```skills\n(.*?)\n```", text, re.DOTALL):
                for ln in block.splitlines():
                    ln = ln.strip()
                    if ln and not ln.startswith("#"):
                        orochi_skills_loaded.append(ln)
    except Exception:
        pass
    return orochi_skills_loaded


def collect_orochi_mcp_servers(workspace: str) -> list[str]:
    """Read the workspace .mcp.json for the loaded MCP server names."""
    orochi_mcp_servers: list[str] = []
    try:
        mcp_path = Path(workspace) / ".mcp.json"
        if mcp_path.is_file():
            doc = json.loads(mcp_path.read_text())
            servers = doc.get("mcpServers") or {}
            if isinstance(servers, dict):
                orochi_mcp_servers = sorted(servers.keys())
    except Exception:
        pass
    return orochi_mcp_servers


def _orochi_claude_md_candidates(ws: str) -> list[Path]:
    """todo#53 prioritised candidate list of CLAUDE.md locations.

    Historically only head-* agents had a CLAUDE.md at
    `<workspace>/CLAUDE.md`. Other roles (healer / skill-manager /
    todo-manager / ...) either live under a legacy `mamba-<name>/`
    directory, use the user's global `~/.claude/CLAUDE.md`, or have
    the file placed in a nested `.claude/` folder.
    """
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


def _orochi_mcp_json_candidates(ws: str) -> list[Path]:
    """todo#53: same fallback logic for .mcp.json so non-head agents populate the MCP viewer."""
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


_TRUNCATE_LIMIT = 10000


def _truncate_with_marker(text: str, limit: int = _TRUNCATE_LIMIT) -> str:
    """Truncate to ``limit`` chars, appending an explicit marker so
    consumers (humans + JSON.parse) can tell the value was cut.

    Returning a hard ``text[:N]`` slice is silent — a long markdown
    code-fence or JSON value gets cut mid-token with no signal.
    Appending ``\\n…(truncated N chars)`` makes the cut self-evident
    in any viewer that doesn't strip trailing whitespace, and the
    leading newline keeps the marker on its own line.
    """
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit] + f"\n…(truncated {omitted} chars)"


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


def collect_orochi_claude_md(workspace: str) -> tuple[str, str]:
    """Return (orochi_claude_md_head, orochi_claude_md_full).

    head: first non-empty heading line (max 120 chars).
    full: full file truncated to 10000 chars.
    """
    orochi_claude_md_head = ""
    orochi_claude_md_full = ""
    for cmd in _orochi_claude_md_candidates(workspace):
        try:
            if cmd.is_file():
                text = cmd.read_text()
                for ln in text.splitlines():
                    ln_stripped = ln.strip()
                    if ln_stripped and not ln_stripped.startswith("```"):
                        orochi_claude_md_head = ln_stripped[:120]
                        break
                orochi_claude_md_full = _truncate_with_marker(text)
                break
        except Exception:
            continue
    return orochi_claude_md_head, orochi_claude_md_full


def collect_orochi_mcp_json(workspace: str) -> str:
    """Return the .mcp.json full content (redacted, truncated to 10000 chars)."""
    orochi_mcp_json_full = ""
    for mcp_path in _orochi_mcp_json_candidates(workspace):
        try:
            if not mcp_path.is_file():
                continue
            doc = json.loads(mcp_path.read_text())
            redacted = _redact_secrets(doc)
            orochi_mcp_json_full = _truncate_with_marker(json.dumps(redacted, indent=2))
            break
        except Exception:
            continue
    return orochi_mcp_json_full


def _orochi_env_file_candidates(ws: str) -> list[Path]:
    """Same fallback logic as CLAUDE.md / .mcp.json — workspace, then sibling
    mamba-* dir, then enclosing git root, then ~/.env."""
    p = Path(ws) if ws else None
    home = Path.home()
    cands: list[Path] = []
    if p is not None:
        cands += [p / ".env"]
        if p.parent.name == "workspaces":
            cands.append(p.parent / f"mamba-{p.name}" / ".env")
        try:
            git_root = p
            while git_root != git_root.parent and not (git_root / ".git").exists():
                git_root = git_root.parent
            if (git_root / ".git").exists():
                cands.append(git_root / ".env")
        except Exception:
            pass
    cands += [home / ".env"]
    seen: set[str] = set()
    uniq: list[Path] = []
    for c in cands:
        key = str(c)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


# Sensitive-key suffixes (whole-token match, NOT substring — the previous
# substring rule matched MONKEY/KEYBASE/LOCALE_KEYBOARD and missed
# DSN/URL/WEBHOOK).
_SENSITIVE_KEY_SUFFIXES = (
    "_TOKEN",
    "_SECRET",
    "_KEY",
    "_KEY_ID",
    "_PASSWORD",
    "_PASS",
    "_PASSWD",
    "_PWD",
    "_CREDENTIAL",
    "_CREDENTIALS",
    "_API_KEY",
    "_PRIVATE_KEY",
    "_DSN",
    "_URL",
    "_WEBHOOK",
    "_HOOK",
    "_CONNECTION_STRING",
    "_CONN_STRING",
    "_CONNSTR",
    "_AUTH",
    "_BEARER",
    "_COOKIE",
    "_SESSION",
)
_SENSITIVE_KEY_EXACT = (
    "TOKEN",
    "SECRET",
    "KEY",
    "PASSWORD",
    "PASS",
    "CREDENTIAL",
    "DSN",
    "URL",
    "WEBHOOK",
    "AUTHORIZATION",
)

# url:user:pw@host pattern — masks the userinfo portion of any URL/DSN.
_DSN_USERINFO_RE = re.compile(r"(?P<scheme>[a-zA-Z][\w+.-]*://)(?P<userinfo>[^/@\s]+@)")

# Multi-line PEM/private-key block markers: anything between
# -----BEGIN ...----- and -----END ...----- is replaced wholesale.
_PEM_BEGIN_RE = re.compile(r"-----BEGIN [A-Z0-9 ]+-----")
_PEM_END_RE = re.compile(r"-----END [A-Z0-9 ]+-----")


def _is_sensitive_key(key_upper: str) -> bool:
    """Return True if a KEY name (already uppercased) should have its
    value redacted entirely.

    Uses suffix-match (so MAILGUN_API_KEY hits, but MONKEY does not) and
    a small set of exact matches for top-level common names like KEY/URL.
    """
    if key_upper in _SENSITIVE_KEY_EXACT:
        return True
    return any(key_upper.endswith(s) for s in _SENSITIVE_KEY_SUFFIXES)


# --- Vendor-detection plugins ------------------------------------------
# We use Yelp's `detect-secrets` library for the vendored-prefix
# detectors (GitHub, AWS, Slack, Anthropic, OpenAI, JWT, Stripe, …) so
# the catalog is maintained for us instead of hand-rolling regex that
# rots whenever a vendor changes its token format. The library's
# high-entropy plugins are explicitly skipped — they have a documented
# false-positive rate on short innocuous strings (the .env file might
# contain `LOCALE=us` and the high-entropy plugin would redact "us").
# We keep our own narrower high-entropy fallback below.
_DETECT_SECRETS_PLUGINS: list = []
_DETECT_SECRETS_AVAILABLE = False
try:  # pragma: no cover — exercised in deployments that pip-install detect-secrets
    from detect_secrets.core.plugins.util import (
        get_mapping_from_secret_type_to_class,
    )

    _DS_SKIP = {
        # entropy-only — too noisy on short fields
        "Base64 High Entropy String",
        "Hex High Entropy String",
        # not a secret type — IP addresses are operational data
        "Public IP (ipv4)",
        # require surrounding context that .env doesn't provide
        "Secret Keyword",
        "Basic Auth Credentials",
    }
    _DETECT_SECRETS_PLUGINS = [
        cls()
        for k, cls in get_mapping_from_secret_type_to_class().items()
        if k not in _DS_SKIP
    ]
    _DETECT_SECRETS_AVAILABLE = True
except ImportError:
    pass


def _vendor_plugins_match(value: str) -> bool:
    """Return True if any maintained vendor-specific plugin
    (GitHub/AWS/Slack/Anthropic/JWT/Stripe/...) flags ``value`` as a
    secret. No-op when the optional `detect-secrets` dep isn't
    available — the structural redaction (key suffix + DSN userinfo)
    plus :func:`_looks_like_high_entropy_token` still defend without it.
    """
    if not _DETECT_SECRETS_AVAILABLE:
        return False
    line = f"X={value}"
    for p in _DETECT_SECRETS_PLUGINS:
        try:
            for _hit in p.analyze_line(filename=".env", line=line, line_number=1):
                return True
        except Exception:
            continue
    return False


def _looks_like_high_entropy_token(value: str) -> bool:
    """Narrow fallback for opaque tokens that a vendor plugin doesn't
    catch (custom internal tokens, generic API gateway keys, etc.).
    Stricter than detect-secrets' built-in high-entropy plugin — we
    require a minimum length AND a base64-/hex-/JWT-shape over the full
    string, so values like "us" or "orochi" don't match.

    Quoted strings are unwrapped before the check.
    """
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()

    # JWT: three dot-separated base64url segments.
    if v.count(".") == 2 and len(v) >= 30:
        parts = v.split(".")
        if all(re.fullmatch(r"[A-Za-z0-9_-]+", p) for p in parts):
            return True

    # Long hex (md5/sha1/sha256/...).
    if len(v) >= 32 and re.fullmatch(r"[0-9a-fA-F]+", v):
        return True

    # Base64 (with / + = padding) — at least 24 chars and predominantly
    # base64 alphabet.
    if len(v) >= 24 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", v):
        return True

    return False


def _redact_env_line(line: str) -> str:
    """Redact secret-shaped values in a single KEY=VALUE line.

    Layered defenses (audit 2026-04-27 §1):

    1. Sensitive key suffix → redact entire value.
    2. URL/DSN userinfo ``scheme://user:pw@host`` → mask userinfo even
       when the key name (``DATABASE_URL`` etc.) slipped the suffix list.
    3. Vendor-specific detectors (`detect-secrets` plugins: GitHub, AWS,
       Slack, Anthropic, OpenAI, JWT, Stripe, …) → catalog maintained
       upstream so we don't rot when a vendor tweaks token format.
    4. Narrow high-entropy fallback for opaque tokens that don't match
       any vendor (custom API gateway keys, internal hashes).
    5. Quoted-value unwrap before steps 3–4 so ``FOO="<token>"`` doesn't
       hide the value behind a quote character.
    """
    # Comment / blank lines pass through.
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return line
    if "=" not in line:
        # Continuation of a previous multi-line value (PEM body, JSON,
        # heredoc) — redact it; we cannot tell whether it's safe.
        return "***REDACTED***"

    key, _, value = line.partition("=")
    key_upper = key.strip().upper()

    if _is_sensitive_key(key_upper):
        return f"{key}=***REDACTED***"

    # DSN / URL userinfo masking: defends DATABASE_URL, REDIS_URL,
    # AMQP_URL, SENTRY_DSN, etc., even when the key name slips past the
    # suffix list.
    if _DSN_USERINFO_RE.search(value):
        masked = _DSN_USERINFO_RE.sub(r"\g<scheme>***REDACTED***@", value)
        return f"{key}={masked}"

    # Unwrap a single matched pair of quotes so the vendor / entropy
    # checks see the bare token.
    bare = value.strip()
    if len(bare) >= 2 and bare[0] == bare[-1] and bare[0] in ("'", '"'):
        bare = bare[1:-1].strip()

    if _vendor_plugins_match(bare) or _looks_like_high_entropy_token(bare):
        return f"{key}=***REDACTED***"

    return line


def _redact_env_text(raw: str) -> str:
    """Redact a full .env text body, line by line, with multi-line
    PEM/JSON awareness. Anything between BEGIN/END PEM markers is
    replaced wholesale; continuation lines (no `=`) are redacted by
    `_redact_env_line` defensively."""
    out: list[str] = []
    in_pem = False
    for line in raw.splitlines():
        if in_pem:
            if _PEM_END_RE.search(line):
                out.append("-----END (REDACTED)-----")
                in_pem = False
            # else: drop the body line entirely.
            continue
        if _PEM_BEGIN_RE.search(line):
            out.append("-----BEGIN (REDACTED)-----")
            in_pem = True
            continue
        out.append(_redact_env_line(line))
    return "\n".join(out)


def collect_orochi_env_file(workspace: str) -> str:
    """Return the workspace .env content (redacted, truncated to
    10000 chars). Empty string when no .env is discoverable.

    Producer-side redaction is the first defense; the hub redacts again on
    render so a future heartbeat path that forgets still stays safe.
    """
    text = ""
    for env_path in _orochi_env_file_candidates(workspace):
        try:
            if not env_path.is_file():
                continue
            raw = env_path.read_text(errors="replace")
            text = _truncate_with_marker(_redact_env_text(raw))
            break
        except Exception:
            continue
    return text
