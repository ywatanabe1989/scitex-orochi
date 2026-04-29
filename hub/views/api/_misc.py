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


def _load_hostname_aliases() -> dict:
    """Read hostname_aliases from the shared fleet config.yaml.

    Returns the map or an empty dict if the file is missing / unparseable.
    """
    import yaml  # noqa: PLC0415 — deferred; yaml not imported at module level

    config_path = os.environ.get(
        "SCITEX_OROCHI_SHARED_CONFIG",
        os.path.expanduser("~/.scitex/orochi/shared/config.yaml"),
    )
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        return dict(cfg.get("spec", {}).get("hostname_aliases", {}) or {})
    except (OSError, yaml.YAMLError):
        return {}


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
        "hostname_aliases": _load_hostname_aliases(),
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


_SUBAGENT_STUCK_THRESHOLD_S = 600  # 10 min non-zero subagent count = stuck


@login_required
@require_GET
def api_watchdog_alerts(request):
    """GET /api/watchdog/alerts/ — current agent staleness alerts.

    Returns agents that need attention:
    1. Agents classified as "stale" (>10min silent) or "idle" (>2min silent)
       AND have an active orochi_current_task.
    2. Agents whose subagent count has been non-zero for >10min with no
       turnover (silent-drop detection — subagents may be wedged).

    Designed to be polled by mamba (or any monitoring client) to drive
    automated nudges and escalation.
    """
    workspace = get_workspace(request)
    from hub.registry import get_agents

    agents = get_agents(workspace_id=workspace.id)
    now = time.time()
    alerts = []
    seen = set()

    for a in agents:
        liveness = a.get("liveness") or a.get("status") or "online"
        idle = a.get("idle_seconds")
        task = (a.get("orochi_current_task") or "").strip()
        name = a["name"]

        # Case 1: idle/stale agent with an active task
        if liveness in ("idle", "stale") and task:
            severity = "stale" if liveness == "stale" else "idle"
            alerts.append(
                {
                    "agent": name,
                    "severity": severity,
                    "kind": "agent_stale",
                    "liveness": liveness,
                    "idle_seconds": idle,
                    "orochi_current_task": task,
                    "machine": a.get("machine", ""),
                    "last_action": a.get("last_action"),
                    "suggested_action": (
                        "escalate" if liveness == "stale" else "nudge"
                    ),
                }
            )
            seen.add(name)

        # Case 2: subagent count non-zero for longer than threshold
        subagent_count = int(a.get("orochi_subagent_count") or 0)
        active_since = a.get("subagent_active_since")
        # orochi#133: corroborate hub-side timer with sac-side LIFO detection.
        # sac_hooks_open_agent_calls_count > 0 means the agent-container's own
        # ring-buffer sees an unmatched Agent pretool — higher confidence the
        # subagent is genuinely stuck (not just a count-update lag).
        open_calls_count = int(a.get("sac_hooks_open_agent_calls_count") or 0)
        oldest_open_age = a.get("sac_hooks_oldest_open_agent_age_s")
        if (
            name not in seen
            and subagent_count > 0
            and active_since is not None
            and (now - float(active_since)) >= _SUBAGENT_STUCK_THRESHOLD_S
        ):
            stuck_secs = int(now - float(active_since))
            alerts.append(
                {
                    "agent": name,
                    "severity": "stale",
                    "kind": "subagent_stuck",
                    "liveness": liveness,
                    "idle_seconds": idle,
                    "orochi_current_task": task,
                    "machine": a.get("machine", ""),
                    "last_action": a.get("last_action"),
                    "subagent_count": subagent_count,
                    "subagent_active_since": active_since,
                    "subagent_stuck_seconds": stuck_secs,
                    # sac-side corroboration (0 / None when sac data absent).
                    "open_agent_calls_count": open_calls_count,
                    "oldest_open_agent_age_s": oldest_open_age,
                    "suggested_action": "escalate",
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
                "subagent_stuck_seconds": _SUBAGENT_STUCK_THRESHOLD_S,
            },
            "ts": timezone.now().isoformat(),
        }
    )


def _machine_liveness(workspace_id: int | None = None) -> dict[str, str]:
    """Return {machine_name: liveness} for all machines with live agents.

    liveness is the worst liveness across that machine's agents:
    "online" > "idle" > "stale" > "offline" (higher = worse).
    """
    from hub.registry import get_agents

    agents = get_agents(workspace_id=workspace_id)
    machine_liveness: dict[str, str] = {}
    _rank = {"online": 0, "idle": 1, "stale": 2, "offline": 3}
    for a in agents:
        m = (a.get("machine") or "").lower().split(".")[0]
        if not m:
            continue
        lv = a.get("liveness", "offline")
        prev_rank = _rank.get(machine_liveness.get(m, "online"), 0)
        new_rank = _rank.get(lv, 3)
        if new_rank > prev_rank:
            machine_liveness[m] = lv
        elif m not in machine_liveness:
            machine_liveness[m] = lv
    return machine_liveness


@login_required
@require_GET
def api_connectivity(request):
    """GET /api/connectivity/ — SSH reachability matrix between known machines.

    Returns a list of nodes (machines) and a list of directional edges
    (source → destination) annotated with reachability and method.

    Topology is static (SSH mesh documented 2026-04-27). Node and bastion
    status is live — derived from the agent registry's per-machine liveness
    (online/idle/stale/offline) so the connectivity map reflects actual
    fleet state rather than a hardcoded "all green" snapshot.

    Per-machine liveness rules:
    - "online": ≥1 agent on that machine has liveness=online
    - "idle": best is idle (all paused/thinking)
    - "stale": ≥1 agent has liveness=stale (connected but stuck)
    - "offline": no live agents on that machine
    """
    workspace = get_workspace(request)
    machine_lv = _machine_liveness(workspace_id=workspace.id)

    def _node_status(machine_id: str) -> str:
        lv = machine_lv.get(machine_id, "offline")
        if lv in ("online", "idle"):
            return "ok"
        if lv == "stale":
            return "stale"
        return "off"

    def _bastion_status(host_machine: str) -> str:
        # Bastion is considered up if the host machine has any live agents.
        return _node_status(host_machine)

    def _edge_status(src: str, dst: str) -> str:
        # Edge is "ok" if destination machine is reachable (has live agents).
        return _node_status(dst)

    # Machine nodes (inner ring) — status derived from live agent registry
    nodes = [
        {
            "id": "ywata-note-win",
            "label": "ywata-note-win",
            "role": "deployer/coordinator",
            "type": "machine",
            "status": _node_status("ywata-note-win"),
            "liveness": machine_lv.get("ywata-note-win", "offline"),
        },
        {
            "id": "mba",
            "label": "mba",
            "role": "orochi-host",
            "type": "machine",
            "status": _node_status("mba"),
            "liveness": machine_lv.get("mba", "offline"),
        },
        {
            "id": "nas",
            "label": "nas",
            "role": "data/scitex-cloud",
            "type": "machine",
            "status": _node_status("nas"),
            "liveness": machine_lv.get("nas", "offline"),
        },
        {
            "id": "spartan",
            "label": "spartan",
            "role": "hpc",
            "type": "machine",
            "status": _node_status("spartan"),
            "liveness": machine_lv.get("spartan", "offline"),
        },
        # Cloudflare bastion nodes (outer ring)
        # Status: inferred from whether the host machine has live agents.
        # If no agents are live on the host, the bastion tunnel is likely down.
        {
            "id": "bastion-win",
            "label": "bastion-win",
            "role": "CF tunnel (bastion-win)",
            "type": "bastion",
            "host": "ywata-note-win",
            "status": _bastion_status("ywata-note-win"),
        },
        {
            "id": "bastion-mba",
            "label": "bastion-mba",
            "role": "CF tunnel (bastion.scitex-orochi.com)",
            "type": "bastion",
            "host": "mba",
            "status": _bastion_status("mba"),
        },
        {
            "id": "bastion-nas",
            "label": "bastion-nas",
            "role": "CF tunnel (bastion.scitex.ai)",
            "type": "bastion",
            "host": "nas",
            "status": _bastion_status("nas"),
        },
        # bastion-spartan REMOVED 2026-04-27 — UniMelb IT Security flagged
        # cloudflared on the HPC login node as a high-severity detection
        # (see scitex-orochi-private/hpc-etiquette.md Incident 2). Spartan is
        # reached via plain `ssh spartan` (public SSH endpoint) and ProxyJump
        # from the other hosts; no Cloudflare tunnel by design.
    ]
    # Source → list of (destination, method) — status derived dynamically
    # 2026-04-27: spartan bastion entry removed; spartan reaches the rest via
    # plain ssh / proxyjump, never via cloudflared.
    raw = [
        # Bastion → host anchors (CF tunnel terminates at machine)
        ("bastion-mba", "mba", "cf-tunnel"),
        ("bastion-nas", "nas", "cf-tunnel"),
        ("bastion-win", "ywata-note-win", "cf-tunnel"),
        # ywata-note-win reaches all
        ("ywata-note-win", "nas", "bastion"),
        ("ywata-note-win", "spartan", "direct"),
        ("ywata-note-win", "mba", "bastion"),
        # NAS reaches all (LAN + bastion)
        ("nas", "ywata-note-win", "tunnel"),
        ("nas", "mba", "lan"),
        ("nas", "spartan", "proxyjump"),
        # MBA reaches all (LAN + bastion + ProxyJump)
        ("mba", "nas", "lan"),
        ("mba", "ywata-note-win", "bastion-win"),
        ("mba", "spartan", "proxyjump"),
        # Spartan reaches via CF bastions
        ("spartan", "mba", "bastion-mba"),
        ("spartan", "nas", "bastion-nas"),
        ("spartan", "ywata-note-win", "bastion-win"),
    ]
    edges = [
        {"source": s, "target": t, "status": _edge_status(s, t), "method": method}
        for (s, t, method) in raw
    ]
    return JsonResponse(
        {
            "nodes": nodes,
            "edges": edges,
            "machine_liveness": machine_lv,
            "source": "live",  # node/edge status derived from agent registry
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
