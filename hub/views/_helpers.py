"""Shared helpers for hub views."""

from django.conf import settings
from django.http import Http404, JsonResponse


def workspace_url(workspace_name, path="/"):
    """Build full URL for a workspace subdomain."""
    base = settings.OROCHI_BASE_DOMAIN
    scheme = "http" if "localhost" in base or "lvh.me" in base else "https"
    return f"{scheme}://{workspace_name}.{base}{path}"


def bare_url(path="/"):
    """Build full URL for the bare domain."""
    base = settings.OROCHI_BASE_DOMAIN
    scheme = "http" if "localhost" in base or "lvh.me" in base else "https"
    return f"{scheme}://{base}{path}"


def get_workspace(request, slug=None):
    """Get workspace from middleware (subdomain) or by ``slug`` kwarg.

    The subdomain middleware sets ``request.workspace`` for hosts of the
    form ``<slug>.scitex-orochi.com``. For test clients (default
    ``testserver`` host) and the path-based ``/api/workspace/<slug>/...``
    routes in :mod:`hub.urls`, the URL kwarg ``slug`` is used as a
    fallback so the same view function works in both contexts.
    """
    workspace = getattr(request, "workspace", None)
    if workspace:
        return workspace
    if slug:
        from hub.models import Workspace

        try:
            return Workspace.objects.get(name=slug)
        except Workspace.DoesNotExist:
            raise Http404(f"Workspace {slug!r} not found")
    raise Http404("No workspace context")


def resolve_workspace_and_actor(request, slug=None):
    """Token-or-session auth helper for agent-callable workspace API views.

    Returns a 3-tuple ``(workspace, actor_member, error_response)``:

    - On Django session auth: ``actor_member`` is the
      :class:`hub.models.WorkspaceMember` for ``request.user`` in the
      resolved workspace; ``error_response`` is ``None``.
    - On workspace-token auth (``?token=wks_...``): the workspace is
      resolved from the token. The actor is taken from the
      ``?agent=<name>`` query param (matching the convention used by
      ``ts/src/config.ts::buildWsUrl`` so MCP sidecars only need to
      forward what they already pass on the WS handshake). If no
      ``?agent=`` is supplied, the actor falls back to the request body
      keys ``agent`` / ``sender`` / ``reactor`` (mirrors the pattern in
      :func:`hub.views.api._reactions.api_reactions`). The synthetic
      ``agent-<name>`` Django user + :class:`hub.models.WorkspaceMember`
      is created on first sight so an agent that just registered can
      open a DM without a separate provisioning step.
    - On any failure: returns ``(None, None, JsonResponse(...))`` with
      a populated 401/404 error.

    Why this exists: the ``@login_required`` decorator that previously
    gated ``api_dms`` etc. doesn't see workspace tokens, so MCP sidecars
    hitting ``https://scitex-orochi.com/api/workspace/<slug>/dms/?token=
    wks_...`` were 302-redirected to ``/signin``. Centralizing the
    branching here keeps the call sites declarative — the view says
    "I need a workspace and an actor" and the helper picks the right
    auth path. Spec v3.1 §4.1 still routes message *sends* through the
    WS path; this helper is for non-write surfaces (DM list/open,
    channel info, history) where REST is the only option.
    """
    import json as _json

    from django.contrib.auth import get_user_model

    from hub.models import WorkspaceMember, WorkspaceToken

    token_str = (
        request.GET.get("token") or (request.POST.get("token") if request.POST else None)
    )

    # ── Session path ────────────────────────────────────────────────
    if not token_str:
        if not (request.user and request.user.is_authenticated):
            return None, None, JsonResponse({"error": "auth required"}, status=401)
        try:
            workspace = get_workspace(request, slug=slug)
        except Http404 as exc:
            return None, None, JsonResponse({"error": str(exc)}, status=404)
        member = (
            WorkspaceMember.objects.filter(workspace=workspace, user=request.user)
            .select_related("user")
            .first()
        )
        if member is None:
            return (
                None,
                None,
                JsonResponse({"error": "not a workspace member"}, status=403),
            )
        return workspace, member, None

    # ── Token path ──────────────────────────────────────────────────
    try:
        wt = WorkspaceToken.objects.select_related("workspace").get(token=token_str)
    except WorkspaceToken.DoesNotExist:
        return None, None, JsonResponse({"error": "invalid token"}, status=401)
    workspace = wt.workspace

    # Actor identity. For agent calls the canonical source is the
    # ``?agent=<name>`` query param; falling back to body keys matches
    # the heterogeneous shapes existing endpoints already accept.
    agent_name = (request.GET.get("agent") or "").strip()
    if not agent_name and request.body:
        try:
            body = _json.loads(request.body or b"{}")
            agent_name = (
                body.get("agent")
                or body.get("sender")
                or body.get("reactor")
                or ""
            ).strip()
        except (_json.JSONDecodeError, ValueError):
            agent_name = ""
    if not agent_name:
        return (
            None,
            None,
            JsonResponse(
                {"error": "agent identity required (pass ?agent=<name>)"},
                status=400,
            ),
        )

    User = get_user_model()
    username = f"agent-{agent_name}"
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            "email": f"{username}@agents.orochi.local",
            "is_active": True,
        },
    )
    member, _ = WorkspaceMember.objects.get_or_create(
        user=user,
        workspace=workspace,
        defaults={"role": "member"},
    )
    return workspace, member, None
