"""Authentication views — signin, signup, signout, invitations."""

import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from hub.models import Channel, Workspace, WorkspaceMember, WorkspaceToken
from hub.views._helpers import bare_url, workspace_url


@require_GET
def agent_login_view(request):
    """GET /agent-login/?token=wks_...&agent=<name>

    Exchange a workspace token for a Django session cookie bound to a
    synthesized agent user. Used by headless browsers (playwright) so
    agents can visit the dashboard for screenshots and visual verification.
    """
    token_str = request.GET.get("token", "").strip()
    agent_name = request.GET.get("agent", "").strip() or "anonymous-agent"
    if not token_str:
        return JsonResponse({"error": "token required"}, status=400)

    try:
        wt = WorkspaceToken.objects.select_related("workspace").get(token=token_str)
    except WorkspaceToken.DoesNotExist:
        return JsonResponse({"error": "invalid token"}, status=401)

    # Synthesize a Django user for this agent — one user per agent name,
    # scoped to the workspace via WorkspaceMember.
    safe_name = re.sub(r"[^a-zA-Z0-9_.\-]", "-", agent_name)
    username = f"agent-{safe_name}"
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            "email": f"{username}@agents.orochi.local",
            "is_active": True,
            "is_staff": False,
        },
    )
    # Ensure the agent is a member of the workspace so permission checks pass
    WorkspaceMember.objects.get_or_create(
        user=user,
        workspace=wt.workspace,
        defaults={"role": "member"},
    )
    # Log the user in without a password — backend must support ModelBackend
    user.backend = "django.contrib.auth.backends.ModelBackend"
    login(request, user)
    return redirect("/")


def signin_view(request):
    """Sign in with username/email and password."""
    if request.user.is_authenticated:
        return redirect("index")

    sso_url = getattr(settings, "SCITEX_OROCHI_SSO_URL", "")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if "@" in username:
            try:
                user_obj = User.objects.get(email=username)
                username = user_obj.username
            except User.DoesNotExist:
                pass

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if getattr(request, "is_bare_domain", False):
                membership = WorkspaceMember.objects.filter(user=user).first()
                if membership:
                    return redirect(workspace_url(membership.workspace.name))
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

        errors = _validate_signup(username, email, password, password2, sso_url)

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            user = User.objects.create_user(
                username=username, email=email, password=password
            )
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "Account created successfully.")

            invite_token = request.POST.get("invite") or request.GET.get("invite")
            if invite_token:
                from hub.models import WorkspaceInvitation

                try:
                    invite = WorkspaceInvitation.objects.get(
                        token=invite_token, accepted=False
                    )
                    WorkspaceMember.objects.get_or_create(
                        workspace=invite.workspace,
                        user=user,
                        defaults={"role": "member"},
                    )
                    invite.accepted = True
                    invite.save()
                    return redirect(workspace_url(invite.workspace.name))
                except WorkspaceInvitation.DoesNotExist:
                    pass

            return redirect("index")

    invite_token = request.GET.get("invite", "")
    return render(
        request, "hub/signup.html", {"sso_url": sso_url, "invite_token": invite_token}
    )


def signout_view(request):
    """Sign out and redirect to signin."""
    logout(request)
    if getattr(request, "is_bare_domain", False):
        return redirect("signin")
    return redirect(bare_url("/signin/"))


def accept_invite_view(request, token):
    """Accept a workspace invitation — sign up if needed, then join."""
    from hub.models import WorkspaceInvitation

    try:
        invite = WorkspaceInvitation.objects.select_related("workspace").get(
            token=token, accepted=False
        )
    except WorkspaceInvitation.DoesNotExist:
        return render(request, "hub/no_access.html", status=404)

    if request.user.is_authenticated:
        WorkspaceMember.objects.get_or_create(
            workspace=invite.workspace,
            user=request.user,
            defaults={"role": "member"},
        )
        invite.accepted = True
        invite.save()
        messages.success(request, f"Joined workspace '{invite.workspace.name}'!")
        return redirect(workspace_url(invite.workspace.name))

    return redirect(f"/signup/?invite={token}")


@login_required
def index(request):
    """Redirect to first workspace subdomain or workspace creation."""
    membership = WorkspaceMember.objects.filter(user=request.user).first()
    if not membership and request.user.is_superuser:
        ws = Workspace.objects.first()
        if ws:
            return redirect(workspace_url(ws.name))

    if membership:
        return redirect(workspace_url(membership.workspace.name))

    return redirect("create-workspace")


@login_required
def create_workspace_view(request):
    """Create a new workspace — like Slack's workspace creation flow."""
    if request.method == "POST":
        name = request.POST.get("name", "").strip().lower()
        description = request.POST.get("description", "").strip()

        errors = []
        if not name:
            errors.append("Workspace name is required.")
        elif not re.match(r"^[a-z0-9][a-z0-9-]*$", name):
            errors.append("Name must be lowercase letters, numbers, and hyphens only.")
        elif len(name) > 50:
            errors.append("Name must be 50 characters or less.")
        elif name in settings.OROCHI_RESERVED_SUBDOMAINS:
            errors.append("This workspace name is reserved.")
        elif Workspace.objects.filter(name=name).exists():
            errors.append("A workspace with this name already exists.")

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            workspace = Workspace.objects.create(name=name, description=description)
            WorkspaceMember.objects.create(
                workspace=workspace, user=request.user, role="admin"
            )
            Channel.objects.create(workspace=workspace, name="#general")
            from hub.models import WorkspaceToken

            token = WorkspaceToken.objects.create(workspace=workspace, label="default")
            messages.success(
                request,
                f"Workspace '{name}' created. Agent token: {token.token}",
            )
            return redirect(workspace_url(name))

    return render(request, "hub/create_workspace.html")


def _validate_signup(username, email, password, password2, sso_url):
    """Validate signup form fields. Returns list of error strings."""
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

    if sso_url and not errors:
        try:
            import requests as req_lib

            resp = req_lib.get(
                f"{sso_url}/auth/api/check-username/",
                params={"username": username},
                timeout=3,
            )
            if resp.status_code == 200:
                data = resp.json()
                if not data.get("available", True):
                    errors.append(
                        "Username is taken on scitex.ai. "
                        "Use 'Sign in with SciTeX' instead."
                    )
        except Exception:
            pass

    return errors
