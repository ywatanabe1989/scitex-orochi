"""Inbound email webhook endpoint — issue #81.

POST /api/inbound-email/
    Receives parsed email fields from a forwarding service (Mailgun, SendGrid,
    Gmail filter → webhook, or any HTTP client) and routes the message to the
    appropriate Orochi channel.

Auth: workspace token in request body (``token`` field) or ``?token=`` param.

Routing priority (first match wins):
  1. ``routing_channel`` field in the request body — explicit override.
  2. ``From:`` header contains ``github.com``      → ``#github``
  3. ``Subject:`` contains ``[CI]`` or ``failure`` → ``#escalation``
  4. Fallback                                       → ``#general``

The ``SCITEX_OROCHI_EMAIL_ROUTES`` env var can override the defaults with a
JSON object mapping regex patterns to channel names, keyed on ``from`` or
``subject``::

    SCITEX_OROCHI_EMAIL_ROUTES='{
        "subject": {"\\\\[alert\\\\]": "#escalation"},
        "from":    {"@github\\\\.com$": "#github"}
    }'
"""

from __future__ import annotations

import json
import os
import re

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse

from hub.models import WorkspaceToken
from hub.views.api._common import get_channel_layer, normalize_channel_name
from hub.consumers._persistence import save_message_sync


# ── Default routing rules ─────────────────────────────────────────────────────

_DEFAULT_FROM_ROUTES: list[tuple[str, str]] = [
    (r"@github\.com", "#github"),
    (r"noreply@github\.com", "#github"),
]

_DEFAULT_SUBJECT_ROUTES: list[tuple[str, str]] = [
    (r"\[CI\]|\bCI\b.*fail|\bfailure\b|\bfailed\b", "#escalation"),
    (r"\balert\b|\bincident\b|\bdown\b", "#escalation"),
    (r"github", "#github"),
]

_FALLBACK_CHANNEL = "#general"


def _load_env_routes() -> dict:
    raw = os.environ.get("SCITEX_OROCHI_EMAIL_ROUTES", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):  # stx-allow: fallback (reason: malformed env var — use defaults)
        return {}


def route_email(from_addr: str, subject: str, routing_channel: str = "") -> str:
    """Return the target channel name for an incoming email.

    Checks explicit override first, then env-var routes, then defaults.
    """
    if routing_channel:
        name = routing_channel if routing_channel.startswith("#") else f"#{routing_channel}"
        return name

    env_routes = _load_env_routes()
    from_patterns: list[tuple[str, str]] = list(env_routes.get("from", {}).items()) + _DEFAULT_FROM_ROUTES
    subject_patterns: list[tuple[str, str]] = list(env_routes.get("subject", {}).items()) + _DEFAULT_SUBJECT_ROUTES

    from_lower = (from_addr or "").lower()
    subject_lower = (subject or "").lower()

    for pattern, channel in from_patterns:
        if re.search(pattern, from_lower, re.IGNORECASE):
            return channel

    for pattern, channel in subject_patterns:
        if re.search(pattern, subject_lower, re.IGNORECASE):
            return channel

    return _FALLBACK_CHANNEL


def _format_email_message(from_addr: str, subject: str, body_text: str) -> str:
    """Format email fields into a readable Orochi message."""
    lines = []
    if subject:
        lines.append(f"**{subject}**")
    if from_addr:
        lines.append(f"From: `{from_addr}`")
    if body_text:
        truncated = body_text[:2000].strip()
        if len(body_text) > 2000:
            truncated += "\n…*(truncated)*"
        lines.append("")
        lines.append(truncated)
    return "\n".join(lines)


@csrf_exempt
@require_http_methods(["POST"])
def api_inbound_email(request):
    """POST /api/inbound-email/ — receive an email and post to a channel.

    Body (JSON or form-encoded):
        token           — workspace token (required)
        from            — sender email address
        subject         — email subject line
        body_text       — plain-text body
        routing_channel — optional channel override (e.g. "#github")
    """
    # ── Parse body ────────────────────────────────────────────────────────────
    content_type = request.content_type or ""
    if "application/json" in content_type:
        try:
            data = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, ValueError):  # stx-allow: fallback (reason: malformed JSON body)
            return JsonResponse({"error": "invalid JSON body"}, status=400)
    else:
        data = request.POST

    token_str = data.get("token") or request.GET.get("token") or ""
    if not token_str:
        return JsonResponse({"error": "token required"}, status=401)

    # ── Auth ──────────────────────────────────────────────────────────────────
    try:
        wt = WorkspaceToken.objects.select_related("workspace").get(token=token_str)
    except WorkspaceToken.DoesNotExist:
        return JsonResponse({"error": "invalid token"}, status=401)

    workspace = wt.workspace

    # ── Extract fields ────────────────────────────────────────────────────────
    from_addr = (data.get("from") or data.get("from_addr") or "").strip()
    subject = (data.get("subject") or "").strip()
    body_text = (data.get("body_text") or data.get("body") or "").strip()
    routing_channel = (data.get("routing_channel") or "").strip()

    if not (from_addr or subject or body_text):
        return JsonResponse({"error": "at least one of from/subject/body_text required"}, status=400)

    # ── Route ─────────────────────────────────────────────────────────────────
    channel_name = route_email(from_addr, subject, routing_channel)
    channel_name = normalize_channel_name(channel_name)

    # ── Persist ───────────────────────────────────────────────────────────────
    text = _format_email_message(from_addr, subject, body_text)
    msg_result = save_message_sync(
        workspace_id=workspace.id,
        channel_name=channel_name,
        sender="inbound-email",
        sender_type="agent",
        content_text=text,
        metadata={"inbound_email": True, "from": from_addr, "subject": subject},
    )
    if msg_result is None:
        return JsonResponse({"error": "failed to persist message"}, status=500)

    msg_id = msg_result["id"]
    msg_ts = msg_result["ts"]

    # ── Broadcast ─────────────────────────────────────────────────────────────
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()
    group_name = f"channel_{workspace.id}_{channel_name}"

    try:
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "chat.message",
                "id": msg_id,
                "sender": "inbound-email",
                "sender_type": "agent",
                "channel": channel_name,
                "text": text,
                "ts": msg_ts,
                "metadata": {"inbound_email": True},
            },
        )
    except Exception:  # stx-allow: fallback (reason: channel layer unavailable — message persisted, broadcast skipped)
        pass

    return JsonResponse(
        {
            "ok": True,
            "channel": channel_name,
            "message_id": msg_id,
        },
        status=201,
    )
