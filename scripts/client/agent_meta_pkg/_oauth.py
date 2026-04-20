"""Claude Code OAuth public metadata reader (todo#265)."""

from __future__ import annotations

import json
from pathlib import Path

from ._log import log


def read_oauth_metadata(claude_json_path=None) -> dict:
    """Return Claude Code OAuth account public metadata (todo#265).

    Reads ``~/.claude.json`` and extracts a strict whitelist of 9
    non-sensitive fields so the Orochi hub's Agents/Activity tab can
    show which account each agent is running under, detect
    out_of_credits state, and support fleet load-balancing.

    SECURITY: This function is whitelist-only. It NEVER reads
    ``~/.claude/.credentials.json`` and NEVER emits any field whose
    name contains ``token``, ``secret``, or ``key``. The final assert
    is a belt-and-braces regression guard against future edits.

    Returns {} on any read/parse error so --push degrades gracefully.
    """
    path = claude_json_path or (Path.home() / ".claude.json")
    try:
        if not path.is_file():
            return {}
        doc = json.loads(path.read_text())
    except Exception as e:
        log.warning("read_oauth_metadata: %s", e)
        return {}
    if not isinstance(doc, dict):
        return {}
    oauth = doc.get("oauthAccount") or {}
    if not isinstance(oauth, dict):
        oauth = {}
    result: dict = {
        "oauth_email": oauth.get("emailAddress") or "",
        "oauth_org_name": oauth.get("organizationName") or "",
        "oauth_account_uuid": oauth.get("accountUuid") or "",
        "oauth_display_name": oauth.get("displayName") or "",
        "billing_type": oauth.get("billingType") or "",
        "has_available_subscription": doc.get("hasAvailableSubscription"),
        "usage_disabled_reason": doc.get("cachedExtraUsageDisabledReason") or "",
        "has_extra_usage_enabled": oauth.get("hasExtraUsageEnabled"),
        "subscription_created_at": oauth.get("subscriptionCreatedAt") or "",
    }
    # Token-leak regression guard (todo#265). If any future edit adds
    # a key containing token/secret/key, this assertion fires BEFORE
    # the data hits the wire.
    assert all(
        "token" not in k.lower()
        and "secret" not in k.lower()
        and "key" not in k.lower()
        for k in result
    ), "read_oauth_metadata: forbidden key in whitelist"
    return result
