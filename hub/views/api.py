"""REST API views for workspace data."""

import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from hub.models import (
    Channel,
    Message,
    MessageReaction,
    MessageThread,
    Workspace,
    WorkspaceMember,
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
def api_channels(request):
    """GET /api/channels/ — list channels in current workspace."""
    workspace = get_workspace(request)
    channels = Channel.objects.filter(workspace=workspace).order_by("name")
    data = [{"name": ch.name, "description": ch.description} for ch in channels]
    return JsonResponse(data, safe=False)


@login_required
@require_http_methods(["GET", "POST"])
def api_messages(request):
    """GET/POST /api/messages/ — recent messages or send one."""
    workspace = get_workspace(request)

    if request.method == "GET":
        limit = min(int(request.GET.get("limit", "100")), 500)
        msgs = (
            Message.objects.filter(workspace=workspace)
            .select_related("channel")
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
                "metadata": m.metadata,
            }
            for m in msgs
        ]
        return JsonResponse(data, safe=False)

    # POST — send a message
    body = json.loads(request.body)
    # Support both flat format {text, channel} and nested {payload: {content, channel}}
    payload = body.get("payload", {})
    ch_name = body.get("channel") or payload.get("channel") or "#general"
    text = body.get("text") or payload.get("content") or payload.get("text") or ""
    attachments = payload.get("attachments") or body.get("attachments") or []
    metadata = payload.get("metadata") or body.get("metadata") or {}
    if attachments:
        metadata = {**metadata, "attachments": attachments}
    if not text and not attachments:
        return JsonResponse({"error": "text or attachments required"}, status=400)

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

    return JsonResponse({"status": "ok", "id": msg.id}, status=201)


@login_required
@require_GET
def api_history(request, channel_name):
    """GET /api/history/<channel>/ — channel message history."""
    workspace = get_workspace(request)
    if not channel_name.startswith("#"):
        channel_name = f"#{channel_name}"

    limit = min(int(request.GET.get("limit", "50")), 500)
    since = request.GET.get("since")

    qs = Message.objects.filter(
        workspace=workspace, channel__name=channel_name
    ).order_by("-ts")

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
            "metadata": m.metadata,
        }
        for m in msgs
    ]
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def api_stats(request):
    """GET /api/stats/ — workspace statistics."""
    workspace = get_workspace(request)
    channels = Channel.objects.filter(workspace=workspace)
    msg_count = Message.objects.filter(workspace=workspace).count()
    member_count = WorkspaceMember.objects.filter(workspace=workspace).count()

    # Count online agents from in-memory registry
    from hub.registry import get_online_count

    agents_online = get_online_count(workspace_id=workspace.id)

    # Deduplicate channel names (safety measure)
    unique_channels = list(dict.fromkeys(ch.name for ch in channels))

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
    data = {
        "workspace": workspace.name,
        "version": version,
        "deployed_at": getattr(settings, "OROCHI_DEPLOYED_AT", ""),
        "build_id": getattr(settings, "OROCHI_BUILD_ID", ""),
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
        {"id": "ywata-note-win", "label": "ywata-note-win", "role": "deployer/coordinator"},
        {"id": "mba", "label": "mba", "role": "orochi-host"},
        {"id": "nas", "label": "nas", "role": "data/scitex-cloud"},
        {"id": "spartan", "label": "spartan", "role": "hpc"},
    ]
    # Source → list of (destination, status, method)
    raw = [
        # ywata-note-win can reach all (deployer)
        ("ywata-note-win", "nas", "ok", "direct"),
        ("ywata-note-win", "spartan", "ok", "direct"),
        ("ywata-note-win", "mba", "ok", "direct"),
        # NAS reaches MBA + win (LAN + reverse tunnel)
        ("nas", "ywata-note-win", "ok", "tunnel"),
        ("nas", "mba", "ok", "lan"),
        ("nas", "spartan", "fail", "blocked-firewall"),
        # MBA reaches NAS + win (LAN + ProxyJump)
        ("mba", "nas", "ok", "lan"),
        ("mba", "ywata-note-win", "ok", "proxyjump"),
        ("mba", "spartan", "fail", "blocked-firewall"),
        # Spartan blocked outbound (HPC firewall)
        ("spartan", "mba", "fail", "blocked-firewall"),
        ("spartan", "nas", "fail", "blocked-firewall"),
        ("spartan", "ywata-note-win", "fail", "blocked-firewall"),
    ]
    edges = [
        {"source": s, "target": t, "status": status, "method": method}
        for (s, t, status, method) in raw
    ]
    return JsonResponse(
        {
            "nodes": nodes,
            "edges": edges,
            "source": "hardcoded",  # will become "live" once basilisk lands
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
        return JsonResponse({"error": "parent_id and text/attachments required"}, status=400)
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
            "text": text,
            "ts": reply.ts.isoformat(),
            "metadata": metadata,
        },
    )
    return JsonResponse({"status": "ok", "reply_id": reply.id}, status=201)


@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def api_reactions(request):
    """Reactions API.

    GET  /api/reactions/?message_ids=1,2,3 — list reactions grouped per message.
    POST /api/reactions/ {message_id, emoji} — toggle reaction by current user.
    DELETE /api/reactions/ {message_id, emoji} — remove reaction by current user.
    """
    workspace = get_workspace(request)

    if request.method == "GET":
        ids_raw = request.GET.get("message_ids", "")
        try:
            ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
        except ValueError:
            ids = []
        if not ids:
            return JsonResponse({}, safe=False)
        qs = (
            MessageReaction.objects.filter(
                message__workspace=workspace, message_id__in=ids
            )
            .values("message_id", "emoji", "reactor", "reactor_type")
        )
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

    reactor = request.user.username
    if request.method == "POST":
        obj, created = MessageReaction.objects.get_or_create(
            message=msg, emoji=emoji, reactor=reactor,
            defaults={"reactor_type": "human"},
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
    url = (
        f"https://api.github.com/repos/{repo}/commits"
        f"?per_page={limit}"
    )
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
            {"error": f"GitHub API returned {e.code}: {e.reason}", "code": "github_error"},
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


@login_required
@require_GET
def api_agents(request):
    """GET /api/agents — list agents from in-memory registry + DB fallback."""
    workspace = get_workspace(request)

    # Primary: in-memory registry (has live metadata from WS connections)
    from hub.registry import get_agents

    registry_agents = get_agents(workspace_id=workspace.id)

    # Fallback: also include agents from recent messages not in registry
    cutoff = timezone.now() - timezone.timedelta(hours=2)
    db_agent_names = set(
        Message.objects.filter(
            workspace=workspace,
            sender_type="agent",
            ts__gte=cutoff,
        ).values_list("sender", flat=True)
    )
    registry_names = {a["name"] for a in registry_agents}

    # Add DB-only agents (not currently in registry)
    for name in db_agent_names - registry_names:
        last_msg = (
            Message.objects.filter(
                workspace=workspace, sender=name, sender_type="agent"
            )
            .order_by("-ts")
            .first()
        )
        last_ts = last_msg.ts.isoformat() if last_msg else None
        channels = list(
            set(
                Message.objects.filter(
                    workspace=workspace, sender=name, sender_type="agent"
                )
                .values_list("channel__name", flat=True)
                .distinct()
            )
        )
        registry_agents.append(
            {
                "name": name,
                "agent_id": name,
                "status": "offline",
                "role": "agent",
                "machine": "",
                "model": "",
                "channels": channels,
                "current_task": "",
                "registered_at": last_ts,
                "last_heartbeat": last_ts,
                "metrics": {},
            }
        )
    return JsonResponse(registry_agents, safe=False)


@login_required
@require_GET
def api_agents_registry(request):
    """GET /api/agents/registry — detailed agent registry (same data as api_agents)."""
    return api_agents(request)


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
        },
    )
    update_heartbeat(name, metrics=body.get("metrics") or {})
    task = body.get("current_task") or ""
    if task:
        set_current_task(name, task)
    preview = body.get("last_message_preview") or ""
    if preview:
        mark_activity(name, action=preview)
    return JsonResponse({"status": "ok", "name": name})


@login_required
@require_http_methods(["POST"])
def api_agents_purge(request):
    """POST /api/agents/purge — remove stale/offline agents from registry.

    Accepts optional JSON body:
        {"agent": "agent-name"}  — purge a specific agent
    Without body, purges all offline agents.
    """
    from hub.registry import purge_agent, purge_all_offline

    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            pass

    agent_name = body.get("agent")
    if agent_name:
        found = purge_agent(agent_name)
        if found:
            return JsonResponse({"status": "ok", "purged": [agent_name]})
        return JsonResponse({"status": "not_found", "purged": []}, status=404)

    count = purge_all_offline()
    return JsonResponse({"status": "ok", "purged_count": count})


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
