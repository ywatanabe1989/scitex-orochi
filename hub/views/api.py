"""REST API views for workspace data."""

import json
import logging
import os
import platform
import time

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

_server_start_time = time.time()


from hub.channel_acl import check_write_allowed
from hub.models import (
    Channel,
    DMParticipant,
    FleetReport,
    Message,
    MessageReaction,
    MessageThread,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
    normalize_channel_name,
)
from hub.views._helpers import get_workspace

log = logging.getLogger("orochi.api")


@login_required
@require_GET
def api_workspaces(request):
    """GET /api/workspaces/ — list workspaces the user can access."""
    if request.user.is_superuser:
        workspaces = Workspace.objects.all()
    else:
        ws_ids = WorkspaceMember.objects.filter(user=request.user).values_list(
            "workspace_id", flat=True
        )
        workspaces = Workspace.objects.filter(id__in=ws_ids)

    base = settings.OROCHI_BASE_DOMAIN
    data = [
        {
            "name": ws.name,
            "description": ws.description,
            "url": f"https://{ws.name}.{base}/",
        }
        for ws in workspaces
    ]
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def api_channels(request, slug=None):
    """GET /api/channels/ — list channels in current workspace."""
    workspace = get_workspace(request, slug=slug)
    channels = Channel.objects.filter(workspace=workspace).order_by("name")
    data = [{"name": ch.name, "description": ch.description} for ch in channels]
    return JsonResponse(data, safe=False)


@login_required
@require_http_methods(["GET", "POST"])
def api_messages(request, slug=None):
    """GET/POST /api/messages/ — recent messages or send one."""
    workspace = get_workspace(request, slug=slug)

    if request.method == "GET":
        from django.db.models import Count, Exists, OuterRef

        limit = min(int(request.GET.get("limit", "100")), 500)
        # Exclude messages that are thread replies (they appear in thread panel only)
        is_thread_reply = Exists(MessageThread.objects.filter(reply_id=OuterRef("pk")))
        msgs = (
            Message.objects.filter(workspace=workspace)
            .exclude(is_thread_reply)
            .exclude(channel__name__startswith="dm:")
            .select_related("channel")
            .annotate(thread_count=Count("thread_replies"))
            .order_by("-ts")[:limit]
        )
        data = [
            {
                "id": m.id,
                "channel": m.channel.name,
                "sender": m.sender,
                "sender_type": m.sender_type,
                "content": m.content,
                "ts": m.ts.isoformat(),
                "edited": m.edited,
                "edited_at": m.edited_at.isoformat() if m.edited_at else None,
                "metadata": m.metadata,
                "thread_count": m.thread_count,
            }
            for m in msgs
        ]
        return JsonResponse(data, safe=False)

    # POST — send a message
    body = json.loads(request.body)
    # Support both flat format {text, channel} and nested {payload: {content, channel}}
    payload = body.get("payload", {})
    # Normalize via the canonical helper so write-path and read-path
    # share the same logic. This subsumes the inline 2-line block that
    # landed on develop in parallel.
    ch_name = normalize_channel_name(
        body.get("channel") or payload.get("channel") or "#general"
    )
    text = body.get("text") or payload.get("content") or payload.get("text") or ""
    attachments = payload.get("attachments") or body.get("attachments") or []
    metadata = payload.get("metadata") or body.get("metadata") or {}
    if attachments:
        metadata = {**metadata, "attachments": attachments}
    if not text and not attachments:
        return JsonResponse({"error": "text or attachments required"}, status=400)

    # Spec v3 §8 / todo#258: REST POST /messages/ previously bypassed
    # the channel write-ACL that AgentConsumer.receive_json enforces.
    # Mirror the same check here so DM confidentiality (and any
    # channels.yaml ACL) is enforced regardless of transport.
    sender_identity = request.user.username
    if not check_write_allowed(
        sender=sender_identity,
        channel=ch_name,
        workspace_id=workspace.id,
    ):
        return JsonResponse(
            {"error": "not allowed to write to this channel"}, status=403
        )

    channel, _ = Channel.objects.get_or_create(workspace=workspace, name=ch_name)
    msg = Message.objects.create(
        workspace=workspace,
        channel=channel,
        sender=request.user.username,
        sender_type="human",
        content=text,
        metadata=metadata,
    )

    layer = get_channel_layer()
    group = f"workspace_{workspace.id}"
    async_to_sync(layer.group_send)(
        group,
        {
            "type": "chat.message",
            "id": msg.id,
            "sender": request.user.username,
            "sender_type": "human",
            "channel": ch_name,
            "text": text,
            "ts": msg.ts.isoformat(),
            "metadata": metadata,
        },
    )

    # Web Push fan-out (todo#263). Best-effort; never block the response.
    try:
        from hub.push import send_push_to_subscribers_async

        send_push_to_subscribers_async(
            workspace_id=workspace.id,
            channel=ch_name,
            sender=request.user.username,
            content=text,
            message_id=msg.id,
        )
    except Exception:
        log.exception("push fan-out failed (REST path)")

    return JsonResponse({"status": "ok", "id": msg.id}, status=201)


@login_required
@require_GET
def api_history(request, channel_name, slug=None):
    """GET /api/history/<channel>/ — channel message history."""
    workspace = get_workspace(request, slug=slug)
    if not channel_name.startswith("#"):
        channel_name = f"#{channel_name}"

    limit = min(int(request.GET.get("limit", "50")), 500)
    since = request.GET.get("since")

    from django.db.models import Count, Exists, OuterRef

    # Exclude thread replies from main channel feed
    is_thread_reply = Exists(MessageThread.objects.filter(reply_id=OuterRef("pk")))
    qs = (
        Message.objects.filter(workspace=workspace, channel__name=channel_name)
        .exclude(is_thread_reply)
        .annotate(thread_count=Count("thread_replies"))
        .order_by("-ts")
    )

    if since:
        qs = qs.filter(ts__gt=since)

    msgs = qs[:limit]
    data = [
        {
            "id": m.id,
            "sender": m.sender,
            "sender_type": m.sender_type,
            "content": m.content,
            "ts": m.ts.isoformat(),
            "edited": m.edited,
            "edited_at": m.edited_at.isoformat() if m.edited_at else None,
            "metadata": m.metadata,
            "thread_count": m.thread_count,
        }
        for m in msgs
    ]
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def api_stats(request, slug=None):
    """GET /api/stats/ — workspace statistics."""
    workspace = get_workspace(request, slug=slug)
    channels = Channel.objects.filter(workspace=workspace)
    msg_count = Message.objects.filter(workspace=workspace).count()
    member_count = WorkspaceMember.objects.filter(workspace=workspace).count()

    # Count online agents from in-memory registry
    from hub.registry import get_online_count

    agents_online = get_online_count(workspace_id=workspace.id)

    # Normalize channel names via the canonical helper, deduplicate,
    # exclude DM channels (they have their own sidebar section).
    # The write-side fix (Channel.save()) makes new rows always canonical;
    # this loop handles legacy rows until migration 0015 backfills them.
    # Use kind field when available, fall back to name prefix as defense.
    seen: set[str] = set()
    unique_channels: list[str] = []
    for ch in channels:
        if ch.kind == Channel.KIND_DM or ch.name.startswith("dm:"):
            continue
        name = normalize_channel_name(ch.name)
        if name not in seen:
            seen.add(name)
            unique_channels.append(name)

    return JsonResponse(
        {
            "workspace": workspace.name,
            "channels": unique_channels,
            "channel_count": len(unique_channels),
            "channels_active": len(unique_channels),
            "message_count": msg_count,
            "member_count": member_count,
            "agents_online": agents_online,
            "observers_connected": member_count,
        }
    )


@login_required
@require_GET
def api_config(request):
    """GET /api/config — dashboard configuration."""
    workspace = get_workspace(request)
    version = getattr(settings, "OROCHI_VERSION", "0.0.0")
    # Server metadata
    uptime_secs = int(time.time() - _server_start_time)
    hostname = os.environ.get("SCITEX_OROCHI_HOSTNAME", platform.node())
    external_ip = os.environ.get("SCITEX_OROCHI_EXTERNAL_IP", "")

    data = {
        "workspace": workspace.name,
        "version": version,
        "deployed_at": getattr(settings, "OROCHI_DEPLOYED_AT", ""),
        "build_id": getattr(settings, "OROCHI_BUILD_ID", ""),
        "server": {
            "hostname": hostname,
            "external_ip": external_ip,
            "uptime": uptime_secs,
            "version": version,
        },
    }
    # Expose dashboard token if set on workspace
    token = request.GET.get("token", "")
    if token:
        data["dashboard_token"] = token
    return JsonResponse(data)


@csrf_exempt
@require_http_methods(["POST"])
def api_event_tool_use(request):
    """POST /api/events/tool-use/ — receive a tool-use event from a Claude Code hook.

    Hooks (PreToolUse/PostToolUse) on each agent's machine POST here to
    record meaningful activity. Updates the in-memory registry's
    last_action timestamp and current_task. Authenticates via workspace
    token query param so hooks don't need Django sessions.

    Body schema:
        {
          "agent": "head@mba",
          "tool": "Edit",
          "phase": "post",          # "pre" or "post"
          "task": "implement #143", # optional, becomes current_task
          "summary": "edited X.py", # optional, short description
          "ts": "2026-04-09T08:00Z" # optional
        }
    """
    token = request.GET.get("token") or request.POST.get("token")
    if token:
        from hub.models import WorkspaceToken

        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "invalid token"}, status=401)
    elif not (request.user and request.user.is_authenticated):
        return JsonResponse({"error": "auth required"}, status=401)

    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    agent = (body.get("agent") or "").strip()
    if not agent:
        return JsonResponse({"error": "agent required"}, status=400)

    from hub.registry import mark_activity, set_current_task

    summary = (body.get("summary") or body.get("tool") or "").strip()[:120]
    mark_activity(agent, action=summary)
    if body.get("task"):
        set_current_task(agent, body.get("task")[:120])
    return JsonResponse({"status": "ok"})


@login_required
@require_GET
def api_watchdog_alerts(request):
    """GET /api/watchdog/alerts/ — current agent staleness alerts.

    Returns agents that need attention: those classified as "stale"
    (>10min silent) or "idle" (>2min silent) AND have an active
    current_task. Designed to be polled by mamba (or any monitoring
    client) to drive automated nudges and escalation.
    """
    workspace = get_workspace(request)
    from hub.registry import get_agents

    agents = get_agents(workspace_id=workspace.id)
    alerts = []
    for a in agents:
        liveness = a.get("liveness") or a.get("status") or "online"
        idle = a.get("idle_seconds")
        task = (a.get("current_task") or "").strip()
        if liveness in ("idle", "stale") and task:
            severity = "stale" if liveness == "stale" else "idle"
            alerts.append(
                {
                    "agent": a["name"],
                    "severity": severity,
                    "liveness": liveness,
                    "idle_seconds": idle,
                    "current_task": task,
                    "machine": a.get("machine", ""),
                    "last_action": a.get("last_action"),
                    "suggested_action": (
                        "escalate" if liveness == "stale" else "nudge"
                    ),
                }
            )
    alerts.sort(key=lambda x: -(x.get("idle_seconds") or 0))
    return JsonResponse(
        {
            "alerts": alerts,
            "count": len(alerts),
            "thresholds": {
                "idle_seconds": 120,
                "stale_seconds": 600,
            },
            "ts": timezone.now().isoformat(),
        }
    )


@login_required
@require_GET
def api_connectivity(request):
    """GET /api/connectivity/ — SSH reachability matrix between known machines.

    Returns a list of nodes (machines) and a list of directional edges
    (source → destination) annotated with reachability and method.

    Currently the matrix is hardcoded from the SSH mesh investigation
    head@ywata-note-win posted earlier in the session. Once basilisk
    (#145 / #144) lands the live discovery, this endpoint will be
    backed by real ping results from the bastion's connectivity probe.
    """
    nodes = [
        {
            "id": "ywata-note-win",
            "label": "ywata-note-win",
            "role": "deployer/coordinator",
        },
        {"id": "mba", "label": "mba", "role": "orochi-host"},
        {"id": "nas", "label": "nas", "role": "data/scitex-cloud"},
        {"id": "spartan", "label": "spartan", "role": "hpc"},
    ]
    # Source → list of (destination, status, method)
    # Updated 2026-04-12: dual bastion (bastion.scitex.ai + bastion.scitex-orochi.com)
    raw = [
        # ywata-note-win can reach all
        ("ywata-note-win", "nas", "ok", "bastion"),
        ("ywata-note-win", "spartan", "ok", "direct"),
        ("ywata-note-win", "mba", "ok", "bastion"),
        # NAS reaches all (LAN + bastion)
        ("nas", "ywata-note-win", "ok", "tunnel"),
        ("nas", "mba", "ok", "lan"),
        ("nas", "spartan", "ok", "proxyjump"),
        # MBA reaches all (LAN + bastion + ProxyJump)
        ("mba", "nas", "ok", "lan"),
        ("mba", "ywata-note-win", "ok", "proxyjump"),
        ("mba", "spartan", "ok", "proxyjump"),
        # Spartan reaches all via bastion (cloudflared)
        ("spartan", "mba", "ok", "bastion"),
        ("spartan", "nas", "ok", "bastion"),
        ("spartan", "ywata-note-win", "ok", "direct"),
    ]
    edges = [
        {"source": s, "target": t, "status": status, "method": method}
        for (s, t, status, method) in raw
    ]
    return JsonResponse(
        {
            "nodes": nodes,
            "edges": edges,
            "source": "static",  # updated 2026-04-12 with bastion mesh
            "ts": timezone.now().isoformat(),
        }
    )


@login_required
@require_http_methods(["GET", "POST"])
def api_threads(request):
    """Thread API — list replies or post a new reply.

    GET  /api/threads/?parent_id=N — list all replies under parent message.
    POST /api/threads/ {parent_id, text, attachments?} — post a reply.
    """
    workspace = get_workspace(request)

    if request.method == "GET":
        try:
            parent_id = int(request.GET.get("parent_id", "0"))
        except ValueError:
            return JsonResponse({"error": "invalid parent_id"}, status=400)
        if not parent_id:
            return JsonResponse({"error": "parent_id required"}, status=400)
        try:
            parent = Message.objects.get(id=parent_id, workspace=workspace)
        except Message.DoesNotExist:
            return JsonResponse({"error": "parent not found"}, status=404)
        thread_rows = (
            MessageThread.objects.filter(parent=parent)
            .select_related("reply", "reply__channel")
            .order_by("ts")
        )
        data = [
            {
                "id": t.reply.id,
                "sender": t.reply.sender,
                "sender_type": t.reply.sender_type,
                "content": t.reply.content,
                "ts": t.reply.ts.isoformat(),
                "metadata": t.reply.metadata,
            }
            for t in thread_rows
        ]
        return JsonResponse(data, safe=False)

    # POST — create a threaded reply
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    parent_id = body.get("parent_id")
    text = body.get("text") or ""
    attachments = body.get("attachments") or []
    if not parent_id or (not text and not attachments):
        return JsonResponse(
            {"error": "parent_id and text/attachments required"}, status=400
        )
    try:
        parent = Message.objects.get(id=parent_id, workspace=workspace)
    except Message.DoesNotExist:
        return JsonResponse({"error": "parent not found"}, status=404)

    metadata = {}
    if attachments:
        metadata["attachments"] = attachments
    reply = Message.objects.create(
        workspace=workspace,
        channel=parent.channel,
        sender=request.user.username,
        sender_type="human",
        content=text,
        metadata=metadata,
    )
    MessageThread.objects.create(parent=parent, reply=reply)

    layer = get_channel_layer()
    group = f"workspace_{workspace.id}"
    async_to_sync(layer.group_send)(
        group,
        {
            "type": "thread.reply",
            "parent_id": parent.id,
            "reply_id": reply.id,
            "sender": request.user.username,
            "sender_type": "human",
            "channel": parent.channel.name,
            "text": text,
            "ts": reply.ts.isoformat(),
            "metadata": metadata,
        },
    )
    return JsonResponse({"status": "ok", "reply_id": reply.id}, status=201)


@csrf_exempt
@require_http_methods(["GET", "POST", "DELETE"])
def api_reactions(request):
    """Reactions API.

    Supports both session auth (browser) and workspace token auth (agents).
    Token can be passed as ?token= query param.

    GET  /api/reactions/?message_ids=1,2,3 — list reactions grouped per message.
    POST /api/reactions/ {message_id, emoji} — toggle reaction by current user.
    DELETE /api/reactions/ {message_id, emoji} — remove reaction by current user.
    """
    # --- auth: token or session ---
    token_str = request.GET.get("token") or request.POST.get("token")
    wks_token = None
    if token_str:
        try:
            wks_token = WorkspaceToken.objects.select_related("workspace").get(
                token=token_str
            )
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "invalid token"}, status=401)
    elif not (request.user and request.user.is_authenticated):
        return JsonResponse({"error": "auth required"}, status=401)

    # --- resolve workspace ---
    if wks_token:
        workspace = wks_token.workspace
    else:
        workspace = get_workspace(request)

    if request.method == "GET":
        ids_raw = request.GET.get("message_ids", "")
        try:
            ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
        except ValueError:
            ids = []
        if not ids:
            return JsonResponse({}, safe=False)
        qs = MessageReaction.objects.filter(
            message__workspace=workspace, message_id__in=ids
        ).values("message_id", "emoji", "reactor", "reactor_type")
        grouped: dict[int, dict[str, list]] = {}
        for r in qs:
            m = grouped.setdefault(r["message_id"], {})
            lst = m.setdefault(r["emoji"], [])
            lst.append({"reactor": r["reactor"], "reactor_type": r["reactor_type"]})
        return JsonResponse(grouped)

    # POST or DELETE — modify
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    message_id = body.get("message_id")
    emoji = (body.get("emoji") or "").strip()
    if not message_id or not emoji:
        return JsonResponse({"error": "message_id and emoji required"}, status=400)
    try:
        msg = Message.objects.get(id=message_id, workspace=workspace)
    except Message.DoesNotExist:
        return JsonResponse({"error": "message not found"}, status=404)

    # Determine reactor identity
    if request.user and request.user.is_authenticated:
        reactor = request.user.username
        reactor_type = "human"
    else:
        reactor = body.get("reactor") or body.get("agent") or "agent"
        reactor_type = "agent"

    if request.method == "POST":
        obj, created = MessageReaction.objects.get_or_create(
            message=msg,
            emoji=emoji,
            reactor=reactor,
            defaults={"reactor_type": reactor_type},
        )
        action = "added" if created else "existed"
    else:  # DELETE
        deleted, _ = MessageReaction.objects.filter(
            message=msg, emoji=emoji, reactor=reactor
        ).delete()
        action = "removed" if deleted else "not_found"

    # Broadcast reaction update to workspace group
    layer = get_channel_layer()
    group = f"workspace_{workspace.id}"
    async_to_sync(layer.group_send)(
        group,
        {
            "type": "reaction.update",
            "message_id": msg.id,
            "emoji": emoji,
            "reactor": reactor,
            "action": action,
        },
    )
    return JsonResponse({"status": "ok", "action": action})


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def api_message_detail(request, message_id):
    """PATCH/DELETE /api/messages/<id>/ — edit or delete a single message.

    Supports both session auth (browser) and workspace token auth (agents).
    Only the original sender can edit. Only the original sender or an admin
    can delete.
    """
    # --- auth: token or session ---
    token_str = request.GET.get("token") or request.POST.get("token")
    wks_token = None
    acting_user = None
    is_admin = False

    if token_str:
        try:
            wks_token = WorkspaceToken.objects.select_related("workspace").get(
                token=token_str
            )
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "invalid token"}, status=401)
    elif not (request.user and request.user.is_authenticated):
        return JsonResponse({"error": "auth required"}, status=401)

    # --- resolve workspace + acting identity ---
    if wks_token:
        workspace = wks_token.workspace
        # For token auth, the sender identity comes from the request body
        try:
            body = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "invalid json"}, status=400)
        acting_user = body.get("sender") or body.get("agent") or "agent"
    else:
        workspace = get_workspace(request)
        acting_user = request.user.username
        is_admin = request.user.is_superuser or WorkspaceMember.objects.filter(
            user=request.user, workspace=workspace, role="admin"
        ).exists()
        try:
            body = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "invalid json"}, status=400)

    # --- fetch message ---
    try:
        msg = Message.objects.select_related("channel").get(
            id=message_id, workspace=workspace
        )
    except Message.DoesNotExist:
        return JsonResponse({"error": "message not found"}, status=404)

    if request.method == "PATCH":
        # Only the original sender can edit
        if msg.sender != acting_user:
            return JsonResponse(
                {"error": "only the original sender can edit"}, status=403
            )
        new_text = body.get("text") or body.get("content")
        if new_text is None:
            return JsonResponse({"error": "text required"}, status=400)

        msg.content = new_text
        msg.edited = True
        msg.edited_at = timezone.now()
        msg.save(update_fields=["content", "edited", "edited_at"])

        # Broadcast edit event
        layer = get_channel_layer()
        group = f"workspace_{workspace.id}"
        async_to_sync(layer.group_send)(
            group,
            {
                "type": "message.edit",
                "message_id": msg.id,
                "sender": msg.sender,
                "channel": msg.channel.name,
                "text": new_text,
                "edited_at": msg.edited_at.isoformat(),
            },
        )
        return JsonResponse({
            "status": "ok",
            "id": msg.id,
            "edited": True,
            "edited_at": msg.edited_at.isoformat(),
        })

    else:  # DELETE
        # Only the original sender or an admin can delete
        if msg.sender != acting_user and not is_admin:
            return JsonResponse(
                {"error": "only the original sender or admin can delete"},
                status=403,
            )
        msg_id = msg.id
        channel_name = msg.channel.name

        msg.delete()

        # Broadcast delete event
        layer = get_channel_layer()
        group = f"workspace_{workspace.id}"
        async_to_sync(layer.group_send)(
            group,
            {
                "type": "message.delete",
                "message_id": msg_id,
                "sender": acting_user,
                "channel": channel_name,
            },
        )
        return JsonResponse({"status": "ok", "id": msg_id, "deleted": True})


@login_required
@require_GET
def api_releases(request):
    """GET /api/releases/ — recent commits sourced from the GitHub API.

    This used to shell `git log` against a container-local `.git` dir, which
    broke whenever the image didn't ship with git/.git (the normal case).
    We now proxy GitHub's commits API using the existing GITHUB_TOKEN, so
    the endpoint works on any stripped image and always reflects what
    `origin` actually has.
    """
    import json
    import os
    import urllib.error
    import urllib.request

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return JsonResponse(
            {"error": "GITHUB_TOKEN not configured", "code": "missing_token"},
            status=503,
        )

    repo = os.environ.get("GITHUB_REPO", "ywatanabe1989/scitex-orochi")
    limit = min(int(request.GET.get("limit", "100")), 100)
    url = f"https://api.github.com/repos/{repo}/commits?per_page={limit}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orochi-Dashboard",
        "Authorization": f"token {token}",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return JsonResponse(
            {
                "error": f"GitHub API returned {e.code}: {e.reason}",
                "code": "github_error",
            },
            status=502,
        )
    except Exception as e:
        return JsonResponse(
            {"error": str(e), "code": "proxy_error"},
            status=502,
        )

    items = []
    for c in raw:
        commit = c.get("commit", {}) or {}
        author = commit.get("author", {}) or {}
        msg = commit.get("message", "") or ""
        subject, _, body = msg.partition("\n")
        items.append(
            {
                "sha": c.get("sha", ""),
                "short_sha": (c.get("sha") or "")[:7],
                "date": author.get("date", ""),
                "author": author.get("name", ""),
                "subject": subject,
                "body": body.strip(),
                "refs": "",
                "url": c.get("html_url", ""),
            }
        )
    return JsonResponse(items, safe=False)


_changelog_cache = {}  # key: "owner/repo" -> (expires_ts, payload_dict)
_CHANGELOG_TTL = 300  # 5 minutes
_CHANGELOG_ALLOWED = {
    "ywatanabe1989/scitex-orochi",
    "ywatanabe1989/scitex-cloud",
    "ywatanabe1989/scitex-python",
    "ywatanabe1989/scitex",
    "ywatanabe1989/scitex-agent-container",
}


@login_required
@require_GET
def api_repo_changelog(request, owner, repo):
    """GET /api/repo/<owner>/<repo>/changelog/ — fetch CHANGELOG.md from a GitHub repo.

    Returns {"content": "<markdown>", "owner": ..., "repo": ...} on success.
    Cached in-process for 5 minutes per (owner, repo) to avoid GitHub rate limits.
    Only repos in the allowlist are accessible.
    """
    import base64
    import json
    import urllib.error
    import urllib.request

    key = f"{owner}/{repo}"
    if key not in _CHANGELOG_ALLOWED:
        return JsonResponse(
            {"error": f"repo not allowed: {key}", "code": "not_allowed"},
            status=403,
        )

    now = time.time()
    cached = _changelog_cache.get(key)
    if cached and cached[0] > now:
        payload = cached[1]
        status = payload.get("_status", 200)
        return JsonResponse(
            {k: v for k, v in payload.items() if not k.startswith("_")},
            status=status,
        )

    token = os.environ.get("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orochi-Dashboard",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/CHANGELOG.md"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read())
        encoded = raw.get("content", "")
        encoding = raw.get("encoding", "base64")
        if encoding == "base64":
            content = base64.b64decode(encoded).decode("utf-8", errors="replace")
        else:
            content = encoded
        payload = {
            "owner": owner,
            "repo": repo,
            "content": content,
            "html_url": raw.get("html_url", ""),
            "_status": 200,
        }
        _changelog_cache[key] = (now + _CHANGELOG_TTL, payload)
        return JsonResponse(
            {k: v for k, v in payload.items() if not k.startswith("_")}
        )
    except urllib.error.HTTPError as e:
        status = 404 if e.code == 404 else 502
        err = {
            "error": f"GitHub API returned {e.code}: {e.reason}",
            "code": "github_error",
            "owner": owner,
            "repo": repo,
            "_status": status,
        }
        _changelog_cache[key] = (now + _CHANGELOG_TTL, err)
        return JsonResponse(
            {k: v for k, v in err.items() if not k.startswith("_")},
            status=status,
        )
    except Exception as e:
        return JsonResponse(
            {"error": str(e), "code": "proxy_error", "owner": owner, "repo": repo},
            status=502,
        )


@login_required
@require_GET
def api_media(request):
    """GET /api/media/ — list all file attachments from message metadata.

    Returns newest-first, with sender, timestamp, channel, and attachment info.
    """
    workspace = get_workspace(request)
    limit = min(int(request.GET.get("limit", "200")), 1000)

    msgs = (
        Message.objects.filter(workspace=workspace)
        .exclude(metadata={})
        .select_related("channel")
        .order_by("-ts")[: limit * 2]  # overshoot — some messages have empty metadata
    )

    items = []
    for m in msgs:
        if not isinstance(m.metadata, dict):
            continue
        attachments = m.metadata.get("attachments") or []
        if not isinstance(attachments, list):
            continue
        for att in attachments:
            if not isinstance(att, dict) or not att.get("url"):
                continue
            items.append(
                {
                    "url": att.get("url"),
                    "filename": att.get("filename") or "",
                    "mime_type": att.get("mime_type") or "",
                    "size": att.get("size") or 0,
                    "sender": m.sender,
                    "sender_type": m.sender_type,
                    "channel": m.channel.name,
                    "ts": m.ts.isoformat(),
                    "message_id": m.id,
                }
            )
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break

    return JsonResponse(items, safe=False)


@login_required
@require_GET
def api_members(request):
    """GET /api/members/ — list human members of the current workspace."""
    workspace = get_workspace(request)
    members = WorkspaceMember.objects.filter(workspace=workspace).select_related("user")
    data = [
        {
            "username": m.user.username,
            "role": m.role,
        }
        for m in members
    ]
    return JsonResponse(data, safe=False)


@require_GET
def api_agents(request):
    """GET /api/agents — list agents from in-memory registry only.

    Auth: Django session OR workspace token (?token=wks_...) so lightweight
    stdlib agents (e.g. caduceus) can poll without a browser login.
    """
    if not (request.user and request.user.is_authenticated):
        token = request.GET.get("token")
        if not token:
            return JsonResponse({"error": "Authentication required"}, status=401)
        from hub.models import WorkspaceToken

        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)
    workspace = get_workspace(request)

    # In-memory registry is the single source of truth for connected agents.
    # No DB fallback — querying Message senders created ghost entries for
    # agents that had disconnected but sent messages recently.
    from hub.registry import get_agents

    registry_agents = get_agents(workspace_id=workspace.id)

    # Merge pinned agents: any pinned agent not in the live registry
    # is added as an "offline" placeholder so the dashboard always shows
    # the expected team roster.
    from hub.models import PinnedAgent

    live_names = {a["name"] for a in registry_agents}
    pinned = PinnedAgent.objects.filter(workspace=workspace)
    for p in pinned:
        if p.name not in live_names:
            registry_agents.append(
                {
                    "name": p.name,
                    "agent_id": p.name,
                    "machine": p.machine,
                    "role": p.role,
                    "model": "",
                    "multiplexer": "",
                    "workdir": "",
                    "icon": "",
                    "icon_emoji": p.icon_emoji,
                    "icon_text": "",
                    "color": getattr(p, "color", ""),
                    "channels": [],
                    "status": "offline",
                    "liveness": "offline",
                    "idle_seconds": None,
                    "registered_at": None,
                    "last_heartbeat": None,
                    "last_action": None,
                    "metrics": {},
                    "current_task": "",
                    "last_message_preview": "",
                    "subagents": [],
                    "subagent_count": 0,
                    "health": {},
                    "claude_md": "",
                    "pinned": True,
                }
            )

    # Tag live agents that are also pinned
    pinned_names = {p.name for p in pinned}
    for a in registry_agents:
        if "pinned" not in a:
            a["pinned"] = a["name"] in pinned_names

    return JsonResponse(registry_agents, safe=False)


@login_required
@require_GET
def api_agents_registry(request):
    """GET /api/agents/registry — detailed agent registry (same data as api_agents)."""
    return api_agents(request)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_agent_profiles(request):
    """GET / POST persistent per-agent display profiles (icon etc).

    GET  — returns all profiles for the current workspace
    POST — upserts one profile: {name, icon_emoji?, icon_image?, icon_text?}

    Both sessions and workspace tokens are accepted.
    """
    # Auth: session OR workspace token
    token = None
    if not (request.user and request.user.is_authenticated):
        body = {}
        if request.method == "POST" and request.body:
            try:
                body = json.loads(request.body)
            except (json.JSONDecodeError, ValueError):
                body = {}
        token = request.GET.get("token") or (
            body.get("token") if isinstance(body, dict) else None
        )
        if not token:
            return JsonResponse({"error": "Authentication required"}, status=401)
        from hub.models import WorkspaceToken

        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)

    workspace = get_workspace(request)
    from hub.models import AgentProfile

    if request.method == "GET":
        profiles = AgentProfile.objects.filter(workspace=workspace)
        data = [
            {
                "name": p.name,
                "icon_emoji": p.icon_emoji,
                "icon_image": p.icon_image,
                "icon_text": p.icon_text,
                "color": p.color,
                "updated_at": p.updated_at.isoformat(),
            }
            for p in profiles
        ]
        return JsonResponse(data, safe=False)

    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    name = (body.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "name required"}, status=400)
    profile, _ = AgentProfile.objects.update_or_create(
        workspace=workspace,
        name=name,
        defaults={
            "icon_emoji": (body.get("icon_emoji") or "")[:16],
            "icon_image": (body.get("icon_image") or "")[:500],
            "icon_text": (body.get("icon_text") or "")[:16],
            "color": (body.get("color") or "")[:16],
        },
    )
    # Push into the in-memory registry so the live card updates too
    from hub.registry import _agents, _lock

    with _lock:
        if name in _agents:
            if profile.icon_emoji:
                _agents[name]["icon_emoji"] = profile.icon_emoji
            if profile.icon_image:
                _agents[name]["icon"] = profile.icon_image
            if profile.icon_text:
                _agents[name]["icon_text"] = profile.icon_text
            if profile.color:
                _agents[name]["color"] = profile.color
    return JsonResponse(
        {
            "status": "ok",
            "name": name,
            "icon_emoji": profile.icon_emoji,
            "icon_image": profile.icon_image,
            "icon_text": profile.icon_text,
            "color": profile.color,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_agent_health(request):
    """POST /api/agents/health/ — caduceus (or any authorized healer)
    records a diagnosis for one or more agents.

    Single:
        {"token":"wks_...", "agent":"head@mba",
         "status":"healthy|idle|stale|stuck_prompt|dead|ghost|unknown",
         "reason":"Simmering… bypass-perms on",
         "source":"caduceus@mba"}

    Bulk:
        {"token":"wks_...", "updates":[{agent, status, reason, source}, ...]}
    """
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    token = body.get("token") or request.GET.get("token")
    if not token:
        return JsonResponse({"error": "token required"}, status=401)
    from hub.models import WorkspaceToken

    try:
        WorkspaceToken.objects.get(token=token)
    except WorkspaceToken.DoesNotExist:
        return JsonResponse({"error": "invalid token"}, status=401)

    from hub.registry import set_health

    updates = body.get("updates")
    if not updates:
        single = body.get("agent")
        if not single:
            return JsonResponse({"error": "agent or updates required"}, status=400)
        updates = [
            {
                "agent": single,
                "status": body.get("status", "unknown"),
                "reason": body.get("reason", ""),
                "source": body.get("source", "caduceus"),
            }
        ]

    applied = 0
    for u in updates:
        name = (u.get("agent") or "").strip()
        if not name:
            continue
        set_health(
            name=name,
            status=u.get("status") or "unknown",
            reason=u.get("reason") or "",
            source=u.get("source") or "caduceus",
        )
        applied += 1
    return JsonResponse({"status": "ok", "applied": applied})


@csrf_exempt
@require_http_methods(["POST"])
def api_subagents_update(request):
    """POST /api/subagents/update — bulk set subagents for one or more agents.

    Intended for caduceus (and any future process-inspector) that can
    enumerate parent→child claude process trees across the fleet and
    push the result here so the Activity tab renders a live subagent
    tree without requiring every agent to cooperate.

    JSON body (either shape):
        {"token": "wks_...", "agent": "head@mba",
         "subagents": [{"name": "...", "task": "...", "status": "running"}]}

    or bulk:
        {"token": "wks_...", "updates": [
            {"agent": "head@mba", "subagents": [...]},
            {"agent": "head@nas", "subagents": [...]}
        ]}
    """
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    token = body.get("token") or request.GET.get("token")
    if not token:
        return JsonResponse({"error": "token required"}, status=401)
    from hub.models import WorkspaceToken

    try:
        WorkspaceToken.objects.get(token=token)
    except WorkspaceToken.DoesNotExist:
        return JsonResponse({"error": "invalid token"}, status=401)

    from hub.registry import set_subagents

    updates = body.get("updates")
    if not updates:
        single_agent = body.get("agent")
        if not single_agent:
            return JsonResponse({"error": "agent or updates required"}, status=400)
        updates = [{"agent": single_agent, "subagents": body.get("subagents") or []}]

    applied = 0
    for u in updates:
        name = (u.get("agent") or "").strip()
        if not name:
            continue
        set_subagents(name, u.get("subagents") or [])
        applied += 1
    return JsonResponse({"status": "ok", "applied": applied})


@csrf_exempt
@require_http_methods(["POST"])
def api_agents_register(request):
    """POST /api/agents/register — REST-level agent registration + heartbeat.

    Intended for lightweight Python/stdlib agents (caduceus) that do not
    run a WebSocket consumer. Accepts JSON:
        {
          "token": "wks_...",
          "name": "caduceus@host",
          "machine": "host",
          "role": "healer",
          "model": "stdlib",
          "channels": ["#general"],
          "current_task": "monitoring"
        }
    Auth: workspace token in body or query string.
    """
    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "invalid json"}, status=400)

    token = body.get("token") or request.GET.get("token")
    if not token:
        return JsonResponse({"error": "token required"}, status=401)

    from hub.models import WorkspaceToken

    try:
        wt = WorkspaceToken.objects.get(token=token)
    except WorkspaceToken.DoesNotExist:
        return JsonResponse({"error": "invalid token"}, status=401)

    name = (body.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "name required"}, status=400)

    from hub.registry import (
        mark_activity,
        register_agent,
        set_current_task,
        update_heartbeat,
    )

    register_agent(
        name=name,
        workspace_id=wt.workspace_id,
        info={
            "agent_id": body.get("agent_id") or name,
            "machine": body.get("machine", ""),
            "role": body.get("role", "agent"),
            "model": body.get("model", ""),
            "workdir": body.get("workdir", ""),
            "channels": body.get("channels") or ["#general"],
            # todo#213: claude-hud-style process/runtime metadata pushed by
            # mamba-healer-mba's agent_meta.py --push loop.
            "multiplexer": body.get("multiplexer", ""),
            "project": body.get("project", ""),
            "pid": body.get("pid") or 0,
            "ppid": body.get("ppid") or 0,
            "context_pct": body.get("context_pct"),
            "skills_loaded": body.get("skills_loaded") or [],
            "started_at": body.get("started_at", ""),
            "version": body.get("version", ""),
            "runtime": body.get("runtime", ""),
            "subagent_count": body.get("subagent_count") or 0,
            # v0.11.0 Agents-tab visibility fields (todo#155). The
            # heartbeat now carries the recent action log, the live
            # tmux pane tail, the workspace CLAUDE.md head, and the
            # MCP server list so the dashboard can render meaningful
            # cards instead of "no task reported".
            "recent_actions": body.get("recent_actions") or [],
            "pane_tail": body.get("pane_tail", ""),
            "pane_tail_block": body.get("pane_tail_block", ""),
            "claude_md_head": body.get("claude_md_head", ""),
            "mcp_servers": body.get("mcp_servers") or [],
            # todo#265: Claude Code OAuth account public metadata
            # (email, org, subscription state). Strict whitelist —
            # never accept access/refresh tokens or credentials.
            "oauth_email": body.get("oauth_email", ""),
            "oauth_org_name": body.get("oauth_org_name", ""),
            "oauth_account_uuid": body.get("oauth_account_uuid", ""),
            "oauth_display_name": body.get("oauth_display_name", ""),
            "billing_type": body.get("billing_type", ""),
            "has_available_subscription": body.get("has_available_subscription"),
            "usage_disabled_reason": body.get("usage_disabled_reason", ""),
            "has_extra_usage_enabled": body.get("has_extra_usage_enabled"),
            "subscription_created_at": body.get("subscription_created_at", ""),
        },
    )
    # Persist subagent_count separately — register_agent() preserves prev
    # value if it exists, so we must set it explicitly on every push to
    # reflect current reality.
    if body.get("subagent_count") is not None:
        from hub.registry import set_subagent_count
        set_subagent_count(name, int(body.get("subagent_count") or 0))
    update_heartbeat(name, metrics=body.get("metrics") or {})
    task = body.get("current_task") or ""
    if task:
        set_current_task(name, task)
    preview = body.get("last_message_preview") or ""
    if preview:
        mark_activity(name, action=preview)
    return JsonResponse({"status": "ok", "name": name})


@csrf_exempt
@require_http_methods(["POST"])
def api_agents_purge(request):
    """POST /api/agents/purge — remove stale/offline agents from registry.

    Accepts optional JSON body:
        {"agent": "agent-name"}  — purge a specific agent
    Without body, purges all offline agents.

    Auth: Django session OR workspace token (?token=wks_... or body.token)
    so caduceus can evict ghost entries without a browser session.
    """
    from hub.registry import purge_agent, purge_all_offline

    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            pass

    if not (request.user and request.user.is_authenticated):
        token = request.GET.get("token") or body.get("token")
        if not token:
            return JsonResponse({"error": "Authentication required"}, status=401)
        from hub.models import WorkspaceToken

        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)

    agent_name = body.get("agent")
    if agent_name:
        found = purge_agent(agent_name)
        if found:
            return JsonResponse({"status": "ok", "purged": [agent_name]})
        return JsonResponse({"status": "not_found", "purged": []}, status=404)

    count = purge_all_offline()
    return JsonResponse({"status": "ok", "purged_count": count})


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_agents_pin(request):
    """POST /api/agents/pin/ — pin an agent so it always appears in dashboard.
    DELETE /api/agents/pin/ — unpin an agent.

    POST body: {"name": "agent-name", "role": "...", "machine": "...", "icon_emoji": "..."}
    DELETE body: {"name": "agent-name"}

    Auth: Django session OR workspace token.
    """
    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            pass

    if not (request.user and request.user.is_authenticated):
        token = request.GET.get("token") or body.get("token")
        if not token:
            return JsonResponse({"error": "Authentication required"}, status=401)
        from hub.models import WorkspaceToken

        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)

    workspace = get_workspace(request)
    name = body.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "name is required"}, status=400)

    from hub.models import PinnedAgent

    if request.method == "POST":
        obj, created = PinnedAgent.objects.update_or_create(
            workspace=workspace,
            name=name,
            defaults={
                "role": body.get("role", ""),
                "machine": body.get("machine", ""),
                "icon_emoji": body.get("icon_emoji", ""),
            },
        )
        return JsonResponse(
            {
                "status": "pinned",
                "name": obj.name,
                "created": created,
            }
        )

    # DELETE
    deleted, _ = PinnedAgent.objects.filter(workspace=workspace, name=name).delete()
    if deleted:
        return JsonResponse({"status": "unpinned", "name": name})
    return JsonResponse({"status": "not_found", "name": name}, status=404)


@login_required
@require_GET
def api_agents_pinned(request):
    """GET /api/agents/pinned/ — list all pinned agents for the workspace."""
    workspace = get_workspace(request)
    from hub.models import PinnedAgent

    pins = PinnedAgent.objects.filter(workspace=workspace)
    data = [
        {
            "name": p.name,
            "role": p.role,
            "machine": p.machine,
            "icon_emoji": p.icon_emoji,
            "added_at": p.added_at.isoformat() if p.added_at else None,
        }
        for p in pins
    ]
    return JsonResponse(data, safe=False)


@csrf_exempt
@require_http_methods(["POST"])
def api_agents_restart(request):
    """POST /api/agents/restart/ — restart an agent's screen session.

    Body: {"name": "head-mba"}

    Auth: Django session OR workspace token.

    The hub SSHs to the agent's host, quits the screen session, and
    relaunches it with claude + dev-channel confirmation.
    """
    import re
    import subprocess

    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            pass

    if not (request.user and request.user.is_authenticated):
        token_str = request.GET.get("token") or body.get("token")
        if not token_str:
            return JsonResponse({"error": "Authentication required"}, status=401)
        try:
            WorkspaceToken.objects.get(token=token_str)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)

    name = body.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "name is required"}, status=400)

    # Validate agent name (alphanumeric, hyphens, underscores only)
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        return JsonResponse({"error": "invalid agent name"}, status=400)

    # Derive host from agent name (same logic as agent_cmd.py)
    def _derive_host(agent_name):
        parts = agent_name.split("-", 1)
        if len(parts) < 2:
            return "localhost"
        machine = parts[1]
        local_hostname = platform.node()
        if machine == local_hostname or machine in local_hostname:
            return "localhost"
        return machine

    host = _derive_host(name)
    is_local = host in ("localhost", "127.0.0.1", "::1", "")
    screen_name = name
    workspace = f"~/.scitex/orochi/workspaces/{name}"

    ssh_prefix = None
    if not is_local:
        ssh_prefix = f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no {host}"

    def _run(cmd):
        if ssh_prefix:
            full = f"{ssh_prefix} bash -lc {_shell_quote(cmd)}"
        else:
            full = cmd
        return subprocess.run(
            full, shell=True, capture_output=True, text=True, timeout=15
        )

    def _shell_quote(s):
        return "'" + s.replace("'", "'\"'\"'") + "'"

    log.info("Restarting agent %s on host %s", name, host)

    # Step 1: Quit existing screen
    quit_cmd = f"screen -S {screen_name} -X quit"
    if ssh_prefix:
        quit_cmd = f"{ssh_prefix} {quit_cmd}"
    try:
        subprocess.run(quit_cmd, shell=True, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        log.warning("Timeout quitting screen for %s", name)

    time.sleep(2)

    # Step 2: Launch new screen session
    claude_cmd = (
        f"cd {workspace} && "
        f"exec claude "
        f"--dangerously-skip-permissions "
        f"--dangerously-load-development-channels server:scitex-orochi"
    )
    screen_cmd = f"screen -dmS {screen_name} bash -lc '{claude_cmd}'"
    try:
        if ssh_prefix:
            result = subprocess.run(
                f"{ssh_prefix} {_shell_quote(screen_cmd)}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
        else:
            result = subprocess.run(
                screen_cmd, shell=True, capture_output=True, text=True, timeout=15
            )
        if result.returncode != 0:
            return JsonResponse(
                {"error": f"screen start failed: {result.stderr.strip()}"},
                status=500,
            )
    except subprocess.TimeoutExpired:
        return JsonResponse({"error": "timeout starting screen"}, status=500)

    # Step 3: Schedule Enter key press after delay (run in background)
    confirm_cmd = f"screen -S {screen_name} -X stuff $'\\r'"
    delay = 8

    def _confirm_dev_channel():
        time.sleep(delay)
        try:
            if ssh_prefix:
                subprocess.run(
                    f"{ssh_prefix} {_shell_quote(confirm_cmd)}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            else:
                subprocess.run(
                    confirm_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
        except Exception:
            log.warning("Failed to confirm dev-channel dialog for %s", name)

    import threading

    threading.Thread(target=_confirm_dev_channel, daemon=True).start()

    log.info("Agent %s restart initiated (Enter in %ds)", name, delay)
    return JsonResponse({"status": "ok", "name": name, "host": host})


@csrf_exempt
@require_http_methods(["POST"])
def api_agents_kill(request):
    """POST /api/agents/kill/ — kill an agent: screen + bun sidecar + WS.

    Body: {"name": "agent-name"}

    Auth: Django session OR workspace token.
    """
    import re
    import subprocess

    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            pass

    if not (request.user and request.user.is_authenticated):
        token_str = request.GET.get("token") or body.get("token")
        if not token_str:
            return JsonResponse({"error": "Authentication required"}, status=401)
        try:
            WorkspaceToken.objects.get(token=token_str)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)

    name = body.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "name is required"}, status=400)

    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        return JsonResponse({"error": "invalid agent name"}, status=400)

    def _derive_host(agent_name):
        parts = agent_name.split("-", 1)
        if len(parts) < 2:
            return "localhost"
        machine = parts[1]
        local_hostname = platform.node()
        if machine == local_hostname or machine in local_hostname:
            return "localhost"
        return machine

    host = _derive_host(name)
    is_local = host in ("localhost", "127.0.0.1", "::1", "")
    screen_name = name

    ssh_prefix = None
    if not is_local:
        ssh_prefix = f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no {host}"

    def _shell_quote(s):
        return "'" + s.replace("'", "'\"'\"'") + "'"

    def _run(cmd):
        if ssh_prefix:
            full = f"{ssh_prefix} bash -lc {_shell_quote(cmd)}"
        else:
            full = cmd
        return subprocess.run(
            full, shell=True, capture_output=True, text=True, timeout=15
        )

    log.info("Killing agent %s on host %s", name, host)
    killed = []

    # Step 1: Kill screen session
    try:
        _run(f"screen -S {screen_name} -X quit")
        killed.append("screen")
    except subprocess.TimeoutExpired:
        log.warning("Timeout killing screen for %s", name)

    # Step 2: Kill bun sidecar (mcp_channel.ts spawned by the screen)
    try:
        # Only kill bun processes associated with this specific agent
        kill_bun_cmd = (
            f"pkill -f 'mcp_channel.ts.*{screen_name}' 2>/dev/null; "
            f"echo done"
        )
        _run(kill_bun_cmd)
        killed.append("bun-sidecar")
    except subprocess.TimeoutExpired:
        log.warning("Timeout killing bun sidecar for %s", name)

    # Step 3: Mark agent offline in registry
    from hub.registry import unregister_agent

    unregister_agent(name)
    killed.append("registry")

    # Step 4: Broadcast presence update
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "dashboard",
            {"type": "agent.presence", "name": name, "status": "offline"},
        )
    except Exception:
        log.warning("Failed to broadcast kill presence for %s", name)

    return JsonResponse({"status": "ok", "name": name, "killed": killed})


@login_required
@require_GET
def api_resources(request):
    """GET /api/resources — resource usage aggregated per machine from agent registry."""
    workspace = get_workspace(request)

    from hub.registry import get_agents

    agents = get_agents(workspace_id=workspace.id)

    # Aggregate by machine hostname (fall back to agent name)
    machines: dict[str, dict] = {}
    for a in agents:
        machine = a.get("machine") or a["name"]
        metrics = a.get("metrics") or {}

        if machine not in machines:
            machines[machine] = {
                "machine": machine,
                "status": a.get("status", "unknown"),
                "last_heartbeat": a.get("last_heartbeat"),
                "agents": [],
                "resources": {
                    "cpu_count": metrics.get("cpu_count", 0),
                    "cpu_model": metrics.get("cpu_model", ""),
                    "load_avg_1m": metrics.get("load_avg_1m", 0),
                    "load_avg_5m": metrics.get("load_avg_5m", 0),
                    "load_avg_15m": metrics.get("load_avg_15m", 0),
                    "mem_used_percent": metrics.get("mem_used_percent", 0),
                    "mem_total_mb": metrics.get("mem_total_mb", 0),
                    "mem_free_mb": metrics.get("mem_free_mb", 0),
                    "disk_used_percent": metrics.get("disk_used_percent", 0),
                },
            }

        machines[machine]["agents"].append(a["name"])

        # Update with latest metrics if this agent has fresher data
        if metrics and a.get("status") == "online":
            res = machines[machine]["resources"]
            for key in (
                "cpu_count",
                "cpu_model",
                "load_avg_1m",
                "load_avg_5m",
                "load_avg_15m",
                "mem_used_percent",
                "mem_total_mb",
                "mem_free_mb",
                "disk_used_percent",
            ):
                val = metrics.get(key)
                if val:
                    res[key] = val
            # Prefer online status
            machines[machine]["status"] = "online"
            if a.get("last_heartbeat"):
                machines[machine]["last_heartbeat"] = a["last_heartbeat"]

    return JsonResponse(machines, safe=False)


# ---------------------------------------------------------------------------
# Direct Messages (spec v3 §4) — todo#60 PR 3
# ---------------------------------------------------------------------------


def _dm_canonical_name(principal_keys):
    """Return the canonical ``dm:<a>|<b>`` channel name for a sorted pair.

    Spec v3 §2.3: DM channel names are ``dm:`` + ``|``-joined sorted
    list of ``<type>:<identity>`` principal keys. Sorting makes the
    name independent of who initiated the DM, so ``get_or_create``
    is naturally idempotent.
    """
    return "dm:" + "|".join(sorted(principal_keys))


def _principal_key_for_member(member):
    """Return ``"agent:<name>"`` or ``"human:<username>"`` for a member."""
    username = member.user.username or ""
    if username.startswith("agent-"):
        return f"agent:{username[len('agent-'):]}"
    return f"human:{username}"


def _resolve_recipient_member(workspace, recipient):
    """Resolve a ``"agent:<name>"`` or ``"human:<username>"`` recipient
    string to a :class:`WorkspaceMember`. Returns ``None`` if the
    recipient is not a member of ``workspace`` or the form is invalid.
    """
    if not recipient or ":" not in recipient:
        return None
    kind, _, identity = recipient.partition(":")
    identity = identity.strip()
    if not identity:
        return None
    if kind == "agent":
        username = f"agent-{identity}"
    elif kind == "human":
        username = identity
    else:
        return None
    return (
        WorkspaceMember.objects.filter(
            workspace=workspace, user__username=username
        )
        .select_related("user")
        .first()
    )


def _dm_row(channel, current_member):
    """Build the row dict returned by GET/POST /dms/."""
    others = []
    for p in channel.dm_participants.select_related("member__user"):
        if p.member_id == current_member.id:
            continue
        others.append(
            {"type": p.principal_type, "identity_name": p.identity_name}
        )
    last_msg = (
        Message.objects.filter(channel=channel).order_by("-ts").only("ts").first()
    )
    return {
        "name": channel.name,
        "kind": channel.kind,
        "other_participants": others,
        "last_message_ts": last_msg.ts.isoformat() if last_msg else None,
    }


@login_required
@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_dms(request, slug=None):
    """GET/POST /api/workspace/<slug>/dms/ — list or create 1:1 DMs.

    Spec v3 §4. The current authenticated principal is resolved via
    ``WorkspaceMember`` for ``request.user`` in the active workspace.
    """
    workspace = get_workspace(request, slug=slug)

    current_member = (
        WorkspaceMember.objects.filter(workspace=workspace, user=request.user)
        .select_related("user")
        .first()
    )
    if current_member is None:
        return JsonResponse(
            {"error": "not a workspace member"}, status=403
        )

    if request.method == "GET":
        my_dm_channel_ids = DMParticipant.objects.filter(
            member=current_member,
            channel__workspace=workspace,
            channel__kind=Channel.KIND_DM,
        ).values_list("channel_id", flat=True)
        channels = Channel.objects.filter(id__in=list(my_dm_channel_ids)).order_by(
            "name"
        )
        rows = [_dm_row(ch, current_member) for ch in channels]
        return JsonResponse({"dms": rows}, safe=False)

    # POST — get-or-create a 1:1 DM
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    recipient = (body.get("recipient") or body.get("peer") or "").strip()
    if not recipient:
        return JsonResponse({"error": "recipient required"}, status=400)

    other_member = _resolve_recipient_member(workspace, recipient)
    if other_member is None:
        return JsonResponse(
            {"error": f"recipient {recipient!r} is not a workspace member"},
            status=404,
        )
    if other_member.id == current_member.id:
        return JsonResponse(
            {"error": "cannot DM yourself"}, status=400
        )

    me_key = _principal_key_for_member(current_member)
    other_key = _principal_key_for_member(other_member)
    canonical_name = _dm_canonical_name([me_key, other_key])

    # Idempotent get-or-create. We do NOT use Channel.objects.get_or_create
    # because we need full_clean() (PR 1 dm: prefix guard) to run on
    # the create path.
    channel = Channel.objects.filter(
        workspace=workspace, name=canonical_name
    ).first()
    if channel is None:
        channel = Channel(
            workspace=workspace,
            name=canonical_name,
            kind=Channel.KIND_DM,
        )
        channel.full_clean()
        channel.save()

    def _principal_type(member):
        return (
            DMParticipant.PRINCIPAL_AGENT
            if (member.user.username or "").startswith("agent-")
            else DMParticipant.PRINCIPAL_HUMAN
        )

    def _identity_name(member):
        username = member.user.username or ""
        if username.startswith("agent-"):
            return username[len("agent-"):]
        return username

    DMParticipant.objects.get_or_create(
        channel=channel,
        member=current_member,
        defaults={
            "principal_type": _principal_type(current_member),
            "identity_name": _identity_name(current_member),
        },
    )
    DMParticipant.objects.get_or_create(
        channel=channel,
        member=other_member,
        defaults={
            "principal_type": _principal_type(other_member),
            "identity_name": _identity_name(other_member),
        },
    )

    return JsonResponse(_dm_row(channel, current_member), status=200)


# ── Web Push (todo#263) ─────────────────────────────────────────────────

@require_GET
def api_push_vapid_key(request):
    """GET /api/push/vapid-key — return the configured VAPID public key.

    Public, unauthenticated. The PWA fetches this before calling
    ``pushManager.subscribe(...)``. Returns an empty string when push
    is unconfigured so the client can degrade gracefully.
    """
    return JsonResponse(
        {"public_key": getattr(settings, "SCITEX_OROCHI_VAPID_PUBLIC", "")}
    )


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def api_push_subscribe(request, slug=None):
    """POST /api/push/subscribe — register a Web Push subscription.

    Body: ``{endpoint, keys: {p256dh, auth}, channels?: [...]}``.
    Idempotent on ``endpoint`` (the unique key on the model).
    """
    from hub.models import PushSubscription

    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    endpoint = body.get("endpoint") or ""
    keys = body.get("keys") or {}
    p256dh = keys.get("p256dh") or ""
    auth = keys.get("auth") or ""
    channels = body.get("channels") or []

    if not endpoint or not p256dh or not auth:
        return JsonResponse(
            {"error": "endpoint, keys.p256dh, keys.auth required"}, status=400
        )

    workspace = None
    try:
        workspace = get_workspace(request, slug=slug)
    except Exception:
        workspace = None

    sub, _created = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": request.user,
            "workspace": workspace,
            "p256dh": p256dh,
            "auth": auth,
            "channels": channels if isinstance(channels, list) else [],
        },
    )
    return JsonResponse({"ok": True, "id": sub.pk})


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def api_push_unsubscribe(request, slug=None):
    """POST /api/push/unsubscribe — drop a subscription by endpoint."""
    from hub.models import PushSubscription

    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    endpoint = body.get("endpoint") or ""
    if not endpoint:
        return JsonResponse({"error": "endpoint required"}, status=400)

    PushSubscription.objects.filter(endpoint=endpoint, user=request.user).delete()
    return JsonResponse({"ok": True})


# Fleet report settings
FLEET_REPORT_MAX_PAYLOAD_KB = 256  # reject payloads > 256KB
FLEET_REPORT_RETENTION_DAYS = 7    # auto-prune reports older than 7 days
FLEET_REPORT_GC_PROBABILITY = 0.05 # 5% chance to run GC on each write


@csrf_exempt
def fleet_report(request):
    """POST /api/fleet/report — accept a fleet report from any producer."""
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    # Validate token and resolve to agent identity
    token = data.get("token") or request.GET.get("token")
    token_obj = WorkspaceToken.objects.filter(token=token).first() if token else None
    if not token_obj:
        return JsonResponse({"error": "unauthorized"}, status=401)

    entity_type = data.get("entity_type")
    entity_id = data.get("entity_id")
    payload = data.get("payload", {})
    source = data.get("source", "unknown")

    if not entity_type or not entity_id:
        return JsonResponse({"error": "entity_type and entity_id required"}, status=400)

    # Tenant scoping: source is forced to token label (no impersonation)
    source = token_obj.label or source

    # Payload size guard
    import sys
    payload_size = sys.getsizeof(json.dumps(payload)) if payload else 0
    if payload_size > FLEET_REPORT_MAX_PAYLOAD_KB * 1024:
        return JsonResponse(
            {"error": f"payload too large ({payload_size} bytes, max {FLEET_REPORT_MAX_PAYLOAD_KB}KB)"},
            status=413,
        )

    report = FleetReport.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        source=source,
    )

    # Probabilistic GC: prune old reports ~5% of writes
    import random
    if random.random() < FLEET_REPORT_GC_PROBABILITY:
        from django.utils import timezone
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=FLEET_REPORT_RETENTION_DAYS)
        FleetReport.objects.filter(ts__lt=cutoff).delete()

    return JsonResponse({"ok": True, "id": report.id, "source": source})


@csrf_exempt
def fleet_state(request):
    """GET /api/fleet/state — query latest state per entity."""
    token = request.GET.get("token")
    if not token or not WorkspaceToken.objects.filter(token=token).exists():
        return JsonResponse({"error": "unauthorized"}, status=401)

    entity_type = request.GET.get("entity_type")
    since = request.GET.get("since")  # ISO timestamp filter

    # Get latest report per entity
    from django.db.models import Max

    qs = FleetReport.objects.all()
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    if since:
        from django.utils.dateparse import parse_datetime
        dt = parse_datetime(since)
        if dt:
            qs = qs.filter(ts__gte=dt)

    # Latest per entity
    latest_ids = (
        qs.values("entity_type", "entity_id")
        .annotate(latest_ts=Max("ts"))
        .values_list("entity_type", "entity_id", "latest_ts")
    )

    results = []
    for et, eid, lts in latest_ids:
        report = qs.filter(entity_type=et, entity_id=eid, ts=lts).first()
        if report:
            results.append({
                "entity_type": report.entity_type,
                "entity_id": report.entity_id,
                "ts": report.ts.isoformat(),
                "payload": report.payload,
                "source": report.source,
            })

    return JsonResponse({"state": results})
