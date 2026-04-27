"""Agent lifecycle: restart and kill (SSH+screen+bun sidecar)."""

from hub.views.api._common import (
    JsonResponse,
    WorkspaceToken,
    csrf_exempt,
    json,
    log,
    platform,
    require_http_methods,
    time,
)


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
            f"pkill -f 'mcp_channel.ts.*{screen_name}' 2>/dev/null; echo done"
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
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "dashboard",
            {"type": "agent.presence", "name": name, "status": "offline"},
        )
    except Exception:
        log.warning("Failed to broadcast kill presence for %s", name)

    return JsonResponse({"status": "ok", "name": name, "killed": killed})
