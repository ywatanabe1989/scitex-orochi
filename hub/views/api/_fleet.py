"""Fleet report/state endpoints + scheduled-actions CRUD."""

from hub.views.api._common import (
    FleetReport,
    JsonResponse,
    WorkspaceToken,
    csrf_exempt,
    json,
    normalize_channel_name,
    require_http_methods,
)

# Fleet report settings
FLEET_REPORT_MAX_PAYLOAD_KB = 256  # reject payloads > 256KB
FLEET_REPORT_RETENTION_DAYS = 7  # auto-prune reports older than 7 days
FLEET_REPORT_GC_PROBABILITY = 0.05  # 5% chance to run GC on each write


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
            {
                "error": f"payload too large ({payload_size} bytes, max {FLEET_REPORT_MAX_PAYLOAD_KB}KB)"
            },
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
        from datetime import timedelta

        from django.utils import timezone

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
            results.append(
                {
                    "entity_type": report.entity_type,
                    "entity_id": report.entity_id,
                    "ts": report.ts.isoformat(),
                    "payload": report.payload,
                    "source": report.source,
                }
            )

    return JsonResponse({"state": results})


# ---------------------------------------------------------------------------
# Scheduled Actions API (issue #95)
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["GET", "POST", "DELETE"])
def api_scheduled(request, slug=None):
    """CRUD for scheduled actions.

    GET  /api/scheduled/          — list pending/all actions
    POST /api/scheduled/          — create a new scheduled action
    DELETE /api/scheduled/?id=N   — cancel an action by id

    Auth: workspace token (query param or JSON body ``token``).
    POST body:
        {
          "token": "wks_...",
          "agent": "mamba-explorer-mba",
          "task": "Investigate X",
          "channel": "#general",        // optional, default #general
          "run_at": "2026-04-14T09:00:00Z",  // ISO8601 UTC
          "cron": "",                   // optional, e.g. "0 9 * * *"
          "created_by": "ywatanabe"     // optional
        }
    """

    from hub.models import ScheduledAction

    def _auth(req):
        token = req.GET.get("token") or ""
        if not token:
            try:
                body = json.loads(req.body or b"{}")
                token = body.get("token", "")
            except Exception:
                pass
        if not token:
            return None, JsonResponse({"error": "token required"}, status=401)
        try:
            ws = WorkspaceToken.objects.select_related("workspace").get(token=token)
            return ws.workspace, None
        except WorkspaceToken.DoesNotExist:
            return None, JsonResponse({"error": "invalid token"}, status=401)

    if request.method == "GET":
        workspace, err = _auth(request)
        if err:
            return err
        status_filter = request.GET.get("status", ScheduledAction.STATUS_PENDING)
        qs = ScheduledAction.objects.filter(workspace=workspace)
        if status_filter != "all":
            qs = qs.filter(status=status_filter)
        items = list(
            qs.values(
                "id",
                "agent",
                "task",
                "channel",
                "run_at",
                "cron",
                "status",
                "created_by",
                "created_at",
                "fired_at",
            )
        )
        for item in items:
            for k in ("run_at", "created_at", "fired_at"):
                if item[k]:
                    item[k] = item[k].isoformat()
        return JsonResponse({"scheduled": items})

    if request.method == "POST":
        workspace, err = _auth(request)
        if err:
            return err
        try:
            body = json.loads(request.body or b"{}")
        except Exception:
            return JsonResponse({"error": "invalid JSON"}, status=400)
        agent = (body.get("agent") or "").strip()
        task = (body.get("task") or "").strip()
        run_at_str = (body.get("run_at") or "").strip()
        if not agent or not task or not run_at_str:
            return JsonResponse({"error": "agent, task, run_at required"}, status=400)
        from django.utils.dateparse import parse_datetime

        run_at = parse_datetime(run_at_str)
        if run_at is None:
            return JsonResponse(
                {"error": "invalid run_at format (use ISO8601)"}, status=400
            )
        if run_at.tzinfo is None:
            import pytz

            run_at = pytz.utc.localize(run_at)
        action = ScheduledAction.objects.create(
            workspace=workspace,
            agent=agent,
            task=task,
            channel=normalize_channel_name(body.get("channel", "general")),
            run_at=run_at,
            cron=body.get("cron", ""),
            created_by=body.get("created_by", ""),
        )
        return JsonResponse(
            {
                "id": action.id,
                "agent": action.agent,
                "run_at": action.run_at.isoformat(),
                "status": action.status,
            },
            status=201,
        )

    if request.method == "DELETE":
        workspace, err = _auth(request)
        if err:
            return err
        action_id = request.GET.get("id")
        if not action_id:
            return JsonResponse({"error": "id required"}, status=400)
        deleted, _ = ScheduledAction.objects.filter(
            workspace=workspace, id=action_id
        ).update(status=ScheduledAction.STATUS_CANCELLED)
        if not deleted:
            ScheduledAction.objects.filter(workspace=workspace, id=action_id).update(
                status=ScheduledAction.STATUS_CANCELLED
            )
        return JsonResponse({"status": "cancelled", "id": action_id})
