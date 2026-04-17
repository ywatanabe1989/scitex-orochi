"""GitHub webhook receiver — POST /webhook/github/

Security: GitHub signs webhook payloads with HMAC-SHA256 using a shared
secret configured when creating the webhook. We verify the
`X-Hub-Signature-256` header before accepting the payload.

Configure in GitHub: URL https://scitex-orochi.com/webhook/github/
with secret from env var GITHUB_WEBHOOK_SECRET.
"""

import hashlib
import hmac
import json
import logging
import os

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from hub.models import Channel, Message, Workspace

log = logging.getLogger("orochi.github")

# Env-var convention: SCITEX_OROCHI_* is the authoritative name. Fall back
# to the legacy bare names (GITHUB_WEBHOOK_*) during rollout so existing
# deployments keep working.
_WEBHOOK_SECRET = os.environ.get(
    "SCITEX_OROCHI_GITHUB_WEBHOOK_SECRET"
) or os.environ.get("GITHUB_WEBHOOK_SECRET", "")
_TARGET_CHANNEL = os.environ.get(
    "SCITEX_OROCHI_GITHUB_WEBHOOK_CHANNEL"
) or os.environ.get("GITHUB_WEBHOOK_CHANNEL", "#progress")


def _verify_signature(body: bytes, header: str) -> bool:
    """Verify GitHub HMAC-SHA256 signature."""
    if not _WEBHOOK_SECRET:
        # No secret configured — reject to be safe
        return False
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        _WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    received = header.split("=", 1)[1]
    return hmac.compare_digest(expected, received)


def _format_event(event: str, payload: dict) -> str | None:
    """Format a GitHub event payload into a human-readable message.

    Returns None if the event/action should be ignored.
    """
    repo = (payload.get("repository") or {}).get("full_name", "?")

    if event == "ping":
        return f"🟢 [{repo}] webhook ping: {payload.get('zen', 'pong')}"

    if event == "workflow_run":
        action = payload.get("action")
        run = payload.get("workflow_run") or {}
        # Only report on completed runs to avoid noise
        if action != "completed":
            return None
        name = run.get("name", "workflow")
        conclusion = run.get("conclusion") or "unknown"
        branch = run.get("head_branch", "?")
        url = run.get("html_url", "")
        head_commit = run.get("head_commit") or {}
        msg = (head_commit.get("message") or "").splitlines()[0] if head_commit else ""
        icon = {
            "success": "🟢",
            "failure": "🔴",
            "cancelled": "⚪",
            "timed_out": "🟠",
            "skipped": "⚪",
        }.get(conclusion, "🟡")
        return (
            f"{icon} [{repo}] {name} {conclusion} on {branch}"
            + (f" - {msg}" if msg else "")
            + (f" - {url}" if url else "")
        )

    if event == "pull_request":
        action = payload.get("action")
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
        title = pr.get("title", "")
        user = (pr.get("user") or {}).get("login", "?")
        url = pr.get("html_url", "")
        if action == "closed" and pr.get("merged"):
            return f"🔀 [{repo}] PR #{number} merged: {title} by {user} - {url}"
        if action == "closed":
            return f"❌ [{repo}] PR #{number} closed: {title} by {user} - {url}"
        if action == "opened":
            return f"📬 [{repo}] PR #{number} opened: {title} by {user} - {url}"
        if action == "reopened":
            return f"♻️ [{repo}] PR #{number} reopened: {title} by {user} - {url}"
        return None

    if event == "push":
        ref = payload.get("ref", "")
        if not ref.startswith("refs/heads/"):
            return None
        branch = ref.split("refs/heads/", 1)[1]
        if branch not in ("main", "master", "develop"):
            return None
        commits = payload.get("commits") or []
        n = len(commits)
        if n == 0:
            return None
        user = (payload.get("pusher") or {}).get("name") or (
            payload.get("sender") or {}
        ).get("login", "?")
        url = payload.get("compare", "")
        return (
            f"⬆️ [{repo}] {n} commit{'s' if n != 1 else ''} pushed to "
            f"{branch} by {user}" + (f" - {url}" if url else "")
        )

    if event == "issues":
        action = payload.get("action")
        issue = payload.get("issue") or {}
        number = issue.get("number")
        title = issue.get("title", "")
        user = (issue.get("user") or {}).get("login", "?")
        url = issue.get("html_url", "")
        if action == "opened":
            return f"📋 [{repo}] Issue #{number} opened: {title} by {user} - {url}"
        if action == "closed":
            return f"✅ [{repo}] Issue #{number} closed: {title} - {url}"
        return None

    if event == "dependabot_alert":
        action = payload.get("action")
        alert = payload.get("alert") or {}
        number = alert.get("number")
        severity = (alert.get("security_advisory") or {}).get("severity", "?")
        pkg = ((alert.get("dependency") or {}).get("package") or {}).get("name", "?")
        summary = (alert.get("security_advisory") or {}).get("summary", "")
        url = alert.get("html_url", "")
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(
            severity.lower(), "⚠️"
        )
        if action in ("created", "auto_opened"):
            return f"{icon} [{repo}] Dependabot alert #{number} [{severity}]: {pkg} — {summary} - {url}"
        if action in ("dismissed", "auto_dismissed", "fixed"):
            return f"✅ [{repo}] Dependabot alert #{number} {action}: {pkg}"
        return None

    if event == "security_advisory":
        advisory = payload.get("security_advisory") or {}
        severity = advisory.get("severity", "?")
        summary = advisory.get("summary", "")
        url = advisory.get("html_url", "")
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(
            severity.lower(), "⚠️"
        )
        return f"{icon} [security_advisory] [{severity}]: {summary} - {url}"

    return None


def _broadcast(text: str, event: str, payload: dict) -> None:
    """Persist and broadcast a system message to the configured channel."""
    workspace = Workspace.objects.first()
    if not workspace:
        log.warning("GitHub webhook: no workspace found, dropping message")
        return

    channel, _ = Channel.objects.get_or_create(
        workspace=workspace, name=_TARGET_CHANNEL
    )
    metadata = {
        "source": "github",
        "github_event": event,
        "github_repo": (payload.get("repository") or {}).get("full_name", ""),
    }
    sender = "github"
    saved = Message.objects.create(
        workspace=workspace,
        channel=channel,
        sender=sender,
        sender_type="system",
        content=text,
        metadata=metadata,
    )

    channel_layer = get_channel_layer()
    if channel_layer:
        group_name = f"workspace_{workspace.id}"
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "chat.message",
                "id": saved.id,
                "sender": sender,
                "sender_type": "system",
                "channel": _TARGET_CHANNEL,
                "text": text,
                "ts": saved.ts.isoformat(),
                "metadata": metadata,
            },
        )


@csrf_exempt
@require_POST
def github_webhook(request):
    """Receive a GitHub webhook event and broadcast it to the channel."""
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(request.body, signature):
        log.warning(
            "GitHub webhook: invalid or missing signature from %s",
            request.META.get("REMOTE_ADDR", "?"),
        )
        return HttpResponse("unauthorized", status=401)

    event = request.headers.get("X-GitHub-Event", "")
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if event == "ping":
        log.info("GitHub webhook: ping received")
        _broadcast(
            _format_event("ping", payload) or "🟢 github webhook ping",
            event,
            payload,
        )
        return JsonResponse({"status": "pong"})

    text = _format_event(event, payload)
    if text is None:
        log.debug(
            "GitHub webhook: ignoring event=%s action=%s", event, payload.get("action")
        )
        return HttpResponse("ok", status=200)

    _broadcast(text, event, payload)
    log.info("GitHub webhook: %s: %s", event, text[:80])
    return HttpResponse("ok", status=200)
