"""Public status page — no auth required (issue #75)."""

import time

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

# Server start time for uptime calculation
_SERVER_START = time.time()


@require_GET
def status_page(request):
    """GET /status/ — public HTML status page."""
    return render(request, "hub/status.html")


@require_GET
@cache_page(15)  # cache for 15 seconds to avoid hammering DB
def api_status(request):
    """GET /api/status/ — public JSON status summary."""
    from hub.models import AgentProfile, Message, Workspace, WorkspaceMember
    from hub.registry import get_agents, get_online_count

    uptime_seconds = int(time.time() - _SERVER_START)
    h, rem = divmod(uptime_seconds, 3600)
    m, s = divmod(rem, 60)
    uptime_str = f"{h}h {m}m {s}s"

    workspace_count = Workspace.objects.count()
    message_count = Message.objects.count()

    agents_online = 0
    agents_total = 0
    agent_list = []
    try:
        all_agents = get_agents()
        agents_total = len(all_agents)
        for a in all_agents:
            online = a.get("status", "") == "online"
            if online:
                agents_online += 1
            agent_list.append(
                {
                    "name": a.get("name", ""),
                    "online": online,
                    "host": a.get("host", ""),
                    "last_seen": a.get("last_seen", ""),
                }
            )
    except Exception:
        pass

    # Last message timestamp across all workspaces
    last_msg = Message.objects.order_by("-ts").values("ts").first()
    last_activity = last_msg["ts"].isoformat() if last_msg else None

    status = "ok"
    if agents_online == 0:
        status = "degraded"

    return JsonResponse(
        {
            "status": status,
            "ts": timezone.now().isoformat(),
            "uptime": uptime_str,
            "uptime_seconds": uptime_seconds,
            "workspaces": workspace_count,
            "messages_total": message_count,
            "last_activity": last_activity,
            "agents": {
                "online": agents_online,
                "total": agents_total,
                "list": agent_list,
            },
        }
    )
