"""Miscellaneous endpoints: config, tool-use events, watchdog alerts,
connectivity matrix, members, web-push subscribe/unsubscribe."""

from hub.views.api._common import (
    JsonResponse,
    WorkspaceMember,
    _server_start_time,
    csrf_exempt,
    get_workspace,
    json,
    login_required,
    os,
    platform,
    require_GET,
    require_http_methods,
    settings,
    time,
    timezone,
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

    Hooks (PreToolUse/PostToolUse) on each agent's orochi_machine POST here to
    record meaningful activity. Updates the in-memory registry's
    last_action timestamp and orochi_current_task. Authenticates via workspace
    token query param so hooks don't need Django sessions.

    Body schema:
        {
          "agent": "head@mba",
          "tool": "Edit",
          "phase": "post",          # "pre" or "post"
          "task": "implement #143", # optional, becomes orochi_current_task
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

    from hub.registry import mark_activity, set_orochi_current_task

    summary = (body.get("summary") or body.get("tool") or "").strip()[:120]
    mark_activity(agent, action=summary)
    if body.get("task"):
        set_orochi_current_task(agent, body.get("task")[:120])
    return JsonResponse({"status": "ok"})


@login_required
@require_GET
def api_watchdog_alerts(request):
    """GET /api/watchdog/alerts/ — current agent staleness alerts.

    Returns agents that need attention: those classified as "stale"
    (>10min silent) or "idle" (>2min silent) AND have an active
    orochi_current_task. Designed to be polled by mamba (or any monitoring
    client) to drive automated nudges and escalation.
    """
    workspace = get_workspace(request)
    from hub.registry import get_agents

    agents = get_agents(workspace_id=workspace.id)
    alerts = []
    for a in agents:
        liveness = a.get("liveness") or a.get("status") or "online"
        idle = a.get("idle_seconds")
        task = (a.get("orochi_current_task") or "").strip()
        if liveness in ("idle", "stale") and task:
            severity = "stale" if liveness == "stale" else "idle"
            alerts.append(
                {
                    "agent": a["name"],
                    "severity": severity,
                    "liveness": liveness,
                    "idle_seconds": idle,
                    "orochi_current_task": task,
                    "orochi_machine": a.get("orochi_machine", ""),
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
    # Machine nodes (inner ring)
    nodes = [
        {
            "id": "ywata-note-win",
            "label": "ywata-note-win",
            "role": "deployer/coordinator",
            "type": "orochi_machine",
        },
        {"id": "mba", "label": "mba", "role": "orochi-host", "type": "orochi_machine"},
        {"id": "nas", "label": "nas", "role": "data/scitex-cloud", "type": "orochi_machine"},
        {"id": "spartan", "label": "spartan", "role": "hpc", "type": "orochi_machine"},
        # Cloudflare bastion nodes (outer ring)
        {
            "id": "bastion-win",
            "label": "bastion-win",
            "role": "CF tunnel (bastion-win)",
            "type": "bastion",
            "host": "ywata-note-win",
        },
        {
            "id": "bastion-mba",
            "label": "bastion-mba",
            "role": "CF tunnel (bastion.scitex-orochi.com)",
            "type": "bastion",
            "host": "mba",
        },
        {
            "id": "bastion-nas",
            "label": "bastion-nas",
            "role": "CF tunnel (bastion.scitex.ai)",
            "type": "bastion",
            "host": "nas",
        },
        # bastion-spartan REMOVED 2026-04-27 — UniMelb IT Security flagged
        # cloudflared on the HPC login node as a high-severity detection
        # (see scitex-orochi-private/hpc-etiquette.md Incident 2). Spartan is
        # reached via plain `ssh spartan` (public SSH endpoint) and ProxyJump
        # from the other hosts; no Cloudflare tunnel by design.
    ]
    # Source → list of (destination, status, method)
    # 2026-04-27: spartan bastion entry removed; spartan reaches the rest via
    # plain ssh / proxyjump, never via cloudflared.
    raw = [
        # Bastion → host anchors (CF tunnel terminates at orochi_machine)
        ("bastion-mba", "mba", "ok", "cf-tunnel"),
        ("bastion-nas", "nas", "ok", "cf-tunnel"),
        ("bastion-win", "ywata-note-win", "ok", "cf-tunnel"),
        # ywata-note-win reaches all
        ("ywata-note-win", "nas", "ok", "bastion"),
        ("ywata-note-win", "spartan", "ok", "direct"),
        ("ywata-note-win", "mba", "ok", "bastion"),
        # NAS reaches all (LAN + bastion)
        ("nas", "ywata-note-win", "ok", "tunnel"),
        ("nas", "mba", "ok", "lan"),
        ("nas", "spartan", "ok", "proxyjump"),
        # MBA reaches all (LAN + bastion + ProxyJump)
        ("mba", "nas", "ok", "lan"),
        ("mba", "ywata-note-win", "ok", "bastion-win"),
        ("mba", "spartan", "ok", "proxyjump"),
        # Spartan reaches via CF bastions
        ("spartan", "mba", "ok", "bastion-mba"),
        ("spartan", "nas", "ok", "bastion-nas"),
        ("spartan", "ywata-note-win", "ok", "bastion-win"),
    ]
    edges = [
        {"source": s, "target": t, "status": status, "method": method}
        for (s, t, status, method) in raw
    ]
    return JsonResponse(
        {
            "nodes": nodes,
            "edges": edges,
            "source": "static",  # 2026-04-27: 3/3 CF mesh (spartan removed; uses plain ssh)
            "ts": timezone.now().isoformat(),
        }
    )


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
    Idempotent on ``endpoint`` (the unique key on the orochi_model).
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
