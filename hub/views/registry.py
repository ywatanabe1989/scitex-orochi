"""Central container-agent registry REST endpoints.

This is a workspace-token-authenticated CRUD surface over the
``ContainerAgent`` orochi_model. It replaces the local-only
``~/.scitex/agent-container/registry/`` directory that scitex-agent-container
writes on each orochi_machine with a hub-hosted, fleet-wide registry.

Distinct from the in-memory WebSocket presence registry (``api_agents``):
this endpoint tracks container/process state (yaml path, orochi_machine, status,
restart history) — not runtime websocket presence.

Endpoints (mounted under both ``urls.py`` and ``urls_bare.py`` so the MCP
sidecar on ``localhost`` can reach them without the subdomain middleware):

    POST   /api/registry/agents/           — register (upsert) a container agent
    GET    /api/registry/agents/           — list all (optional ?orochi_machine=, ?status=)
    PATCH  /api/registry/agents/<name>/    — update status / last_seen / metadata
    DELETE /api/registry/agents/<name>/    — unregister

All endpoints require a ``wks_...`` workspace token (body/query/header).
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hub.models import ContainerAgent, WorkspaceToken


def _extract_token(request, body):
    return (
        request.GET.get("token")
        or (body.get("token") if isinstance(body, dict) else None)
        or request.headers.get("X-Orochi-Token")
        or ""
    ).strip()


def _authenticate(request, body):
    """Resolve the workspace from a token, or return a JsonResponse error."""
    token = _extract_token(request, body)
    if not token:
        return None, JsonResponse({"error": "token required"}, status=401)
    try:
        wt = WorkspaceToken.objects.select_related("workspace").get(token=token)
    except WorkspaceToken.DoesNotExist:
        return None, JsonResponse({"error": "invalid token"}, status=401)
    return wt.workspace, None


def _parse_body(request):
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else {}


def _serialize(agent):
    return {
        "name": agent.name,
        "orochi_machine": agent.orochi_machine,
        "yaml_path": agent.yaml_path,
        "status": agent.status,
        "workspace": agent.workspace.name,
        "started_at": agent.started_at.isoformat(),
        "last_seen": agent.last_seen.isoformat(),
        "metadata": agent.metadata or {},
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_registry_agents(request):
    """GET (list) or POST (register/upsert) container agents."""
    if request.method == "GET":
        body = {}
    else:
        body = _parse_body(request)
        if body is None:
            return JsonResponse({"error": "invalid json"}, status=400)

    workspace, err = _authenticate(request, body)
    if err:
        return err

    if request.method == "GET":
        qs = ContainerAgent.objects.filter(workspace=workspace)
        orochi_machine = request.GET.get("orochi_machine")
        if orochi_machine:
            qs = qs.filter(orochi_machine=orochi_machine)
        status_filter = request.GET.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return JsonResponse(
            {"agents": [_serialize(a) for a in qs]}, safe=False
        )

    # POST — upsert by unique name
    name = (body.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "name required"}, status=400)
    orochi_machine = (body.get("orochi_machine") or "").strip()
    if not orochi_machine:
        return JsonResponse({"error": "orochi_machine required"}, status=400)

    status_val = (body.get("status") or ContainerAgent.Status.RUNNING).strip()
    if status_val not in dict(ContainerAgent.Status.choices):
        return JsonResponse(
            {"error": f"invalid status '{status_val}'"}, status=400
        )

    defaults = {
        "workspace": workspace,
        "orochi_machine": orochi_machine,
        "yaml_path": (body.get("yaml_path") or "")[:500],
        "status": status_val,
        "metadata": body.get("metadata") or {},
    }
    agent, created = ContainerAgent.objects.update_or_create(
        name=name, defaults=defaults
    )
    return JsonResponse(
        {"status": "ok", "created": created, "agent": _serialize(agent)},
        status=201 if created else 200,
    )


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def api_registry_agent_detail(request, name):
    """PATCH (update status/metadata) or DELETE (unregister) one container agent."""
    body = _parse_body(request)
    if body is None:
        return JsonResponse({"error": "invalid json"}, status=400)

    workspace, err = _authenticate(request, body)
    if err:
        return err

    try:
        agent = ContainerAgent.objects.get(workspace=workspace, name=name)
    except ContainerAgent.DoesNotExist:
        return JsonResponse({"error": "not found"}, status=404)

    if request.method == "DELETE":
        agent.delete()
        return JsonResponse({"status": "ok", "deleted": name})

    # PATCH
    changed = False
    if "status" in body:
        new_status = (body.get("status") or "").strip()
        if new_status not in dict(ContainerAgent.Status.choices):
            return JsonResponse(
                {"error": f"invalid status '{new_status}'"}, status=400
            )
        agent.status = new_status
        changed = True
    if "yaml_path" in body:
        agent.yaml_path = (body.get("yaml_path") or "")[:500]
        changed = True
    if "orochi_machine" in body:
        agent.orochi_machine = (body.get("orochi_machine") or "").strip() or agent.orochi_machine
        changed = True
    if "metadata" in body and isinstance(body.get("metadata"), dict):
        # Shallow-merge so callers can patch individual keys (e.g. restart_count)
        merged = dict(agent.metadata or {})
        merged.update(body["metadata"])
        agent.metadata = merged
        changed = True

    # Always bump last_seen on PATCH — it's effectively a heartbeat.
    agent.save()  # auto_now last_seen fires here
    return JsonResponse(
        {"status": "ok", "changed": changed, "agent": _serialize(agent)}
    )
