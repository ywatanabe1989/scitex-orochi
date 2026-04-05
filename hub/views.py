"""Views for the Orochi hub — dashboard and REST API."""

import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from hub.models import Channel, Message, Workspace, WorkspaceMember

# --- Auth views ---


def signin_view(request):
    """Sign in with username/email and password."""
    if request.user.is_authenticated:
        return redirect("index")

    sso_url = getattr(settings, "SCITEX_OROCHI_SSO_URL", "")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        # Allow login with email
        if "@" in username:
            try:
                user_obj = User.objects.get(email=username)
                username = user_obj.username
            except User.DoesNotExist:
                pass

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get("next", "/")
            return redirect(next_url)
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "hub/signin.html", {"sso_url": sso_url})


def signup_view(request):
    """Create a new account."""
    if request.user.is_authenticated:
        return redirect("index")

    sso_url = getattr(settings, "SCITEX_OROCHI_SSO_URL", "")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")

        import re

        errors = []
        if not username:
            errors.append("Username is required.")
        if not email:
            errors.append("Email is required.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if not re.search(r"[a-z]", password):
            errors.append("Password must contain a lowercase letter.")
        if not re.search(r"[A-Z]", password):
            errors.append("Password must contain an uppercase letter.")
        if not re.search(r"\d", password):
            errors.append("Password must contain a number.")
        if not re.search(r"[^a-zA-Z0-9]", password):
            errors.append("Password must contain a special character.")
        if password != password2:
            errors.append("Passwords do not match.")
        if User.objects.filter(username=username).exists():
            errors.append("Username is already taken.")
        if User.objects.filter(email=email).exists():
            errors.append("Email is already registered.")

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            user = User.objects.create_user(
                username=username, email=email, password=password
            )
            login(request, user)
            messages.success(request, "Account created successfully.")
            return redirect("index")

    return render(request, "hub/signup.html", {"sso_url": sso_url})


def signout_view(request):
    """Sign out and redirect to signin."""
    logout(request)
    return redirect("signin")


@login_required
def index(request):
    """Redirect to the user's first workspace or show workspace list."""
    if request.user.is_superuser:
        workspace = Workspace.objects.first()
    else:
        membership = WorkspaceMember.objects.filter(user=request.user).first()
        workspace = membership.workspace if membership else None

    if workspace:
        return redirect("workspace-dashboard", slug=workspace.name)

    return render(request, "hub/no_workspace.html")


@login_required
def workspace_dashboard(request, slug):
    """Main dashboard view for a workspace."""
    workspace = get_object_or_404(Workspace, name=slug)

    # Check access
    if not request.user.is_superuser:
        if not WorkspaceMember.objects.filter(
            user=request.user, workspace=workspace
        ).exists():
            return render(request, "hub/no_access.html", status=403)

    channels = Channel.objects.filter(workspace=workspace).order_by("name")
    return render(
        request,
        "hub/dashboard.html",
        {
            "workspace": workspace,
            "channels": channels,
        },
    )


# --- REST API ---


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

    data = [{"name": ws.name, "description": ws.description} for ws in workspaces]
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def api_channels(request, slug):
    """GET /api/workspace/<slug>/channels/ — list channels."""
    workspace = get_object_or_404(Workspace, name=slug)
    channels = Channel.objects.filter(workspace=workspace).order_by("name")
    data = [{"name": ch.name, "description": ch.description} for ch in channels]
    return JsonResponse(data, safe=False)


@login_required
@require_http_methods(["GET", "POST"])
def api_messages(request, slug):
    """GET/POST /api/workspace/<slug>/messages/ — recent messages or send one."""
    workspace = get_object_or_404(Workspace, name=slug)

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
                "content": m.content,
                "ts": m.ts.isoformat(),
                "metadata": m.metadata,
            }
            for m in msgs
        ]
        return JsonResponse(data, safe=False)

    # POST — send a message
    body = json.loads(request.body)
    ch_name = body.get("channel", "#general")
    text = body.get("text", "")
    if not text:
        return JsonResponse({"error": "text is required"}, status=400)

    channel, _ = Channel.objects.get_or_create(workspace=workspace, name=ch_name)
    msg = Message.objects.create(
        workspace=workspace,
        channel=channel,
        sender=request.user.username,
        content=text,
    )

    # Broadcast via channel layer
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    group = f"workspace_{workspace.id}"
    async_to_sync(layer.group_send)(
        group,
        {
            "type": "chat.message",
            "sender": request.user.username,
            "channel": ch_name,
            "text": text,
            "ts": msg.ts.isoformat(),
        },
    )

    return JsonResponse({"status": "ok", "id": msg.id}, status=201)


@login_required
@require_GET
def api_history(request, slug, channel_name):
    """GET /api/workspace/<slug>/history/<channel>/ — channel message history."""
    workspace = get_object_or_404(Workspace, name=slug)
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
            "content": m.content,
            "ts": m.ts.isoformat(),
            "metadata": m.metadata,
        }
        for m in msgs
    ]
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def api_stats(request, slug):
    """GET /api/workspace/<slug>/stats/ — workspace statistics."""
    workspace = get_object_or_404(Workspace, name=slug)
    channels = Channel.objects.filter(workspace=workspace)
    msg_count = Message.objects.filter(workspace=workspace).count()
    member_count = WorkspaceMember.objects.filter(workspace=workspace).count()

    return JsonResponse(
        {
            "workspace": workspace.name,
            "channels": [ch.name for ch in channels],
            "channel_count": channels.count(),
            "message_count": msg_count,
            "member_count": member_count,
        }
    )
