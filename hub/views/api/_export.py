"""Channel export + media listing API views."""

from hub.views.api._common import (
    Channel,
    JsonResponse,
    Message,
    WorkspaceToken,
    csrf_exempt,
    datetime,
    dt_timezone,
    get_workspace,
    json,
    login_required,
    normalize_channel_name,
    require_GET,
)


@csrf_exempt
@require_GET
def api_channel_export(request, chat_id, slug=None):
    """GET /api/channels/<chat_id>/export/ — export channel messages.

    Query params:
      from    ISO8601 or YYYY-MM-DD, inclusive lower bound (default: beginning)
      to      ISO8601 or YYYY-MM-DD, inclusive upper bound (default: now)
      format  json|md|txt (default: json)
      token   workspace token for auth

    Output formats:
      json — NDJSON, one message per line
      md   — markdown with date/time headers
      txt  — plain text: [date time] sender: text
    """
    # --- auth: token or session ---
    token_str = request.GET.get("token")
    workspace = None
    if token_str:
        try:
            wks_token = WorkspaceToken.objects.select_related("workspace").get(
                token=token_str
            )
            workspace = wks_token.workspace
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "invalid token"}, status=401)
    elif request.user and request.user.is_authenticated:
        workspace = get_workspace(request, slug=slug)
    else:
        return JsonResponse({"error": "auth required"}, status=401)

    # --- resolve channel ---
    channel_name = normalize_channel_name(chat_id)
    try:
        channel = Channel.objects.get(workspace=workspace, name=channel_name)
    except Channel.DoesNotExist:
        return JsonResponse({"error": "channel not found"}, status=404)

    # --- parse date bounds ---
    def _parse_dt(s, end_of_day=False):
        """Parse ISO8601 or YYYY-MM-DD into aware datetime."""
        if not s:
            return None
        # Try YYYY-MM-DD
        try:
            d = datetime.strptime(s, "%Y-%m-%d")
            if end_of_day:
                d = d.replace(hour=23, minute=59, second=59, microsecond=999999)
            return d.replace(tzinfo=dt_timezone.utc)
        except ValueError:
            pass
        # Try ISO8601 with or without timezone
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=dt_timezone.utc)
                return dt
            except ValueError:
                continue
        return None

    from_dt = _parse_dt(request.GET.get("from"), end_of_day=False)
    to_dt = _parse_dt(request.GET.get("to"), end_of_day=True)
    fmt = request.GET.get("format", "json").lower()
    if fmt not in ("json", "md", "txt"):
        return JsonResponse({"error": "format must be json, md, or txt"}, status=400)

    # --- query messages ---
    qs = Message.objects.filter(
        workspace=workspace,
        channel=channel,
        deleted_at__isnull=True,
    ).order_by("ts")
    if from_dt:
        qs = qs.filter(ts__gte=from_dt)
    if to_dt:
        qs = qs.filter(ts__lte=to_dt)

    # --- build content ---
    def _attachments(msg):
        return msg.metadata.get("attachments", []) if msg.metadata else []

    if fmt == "json":
        lines = []
        for m in qs:
            lines.append(
                json.dumps(
                    {
                        "msg_id": m.id,
                        "ts": m.ts.isoformat(),
                        "chat_id": channel_name,
                        "user": m.sender,
                        "text": m.content,
                        "attachments": _attachments(m),
                    },
                    ensure_ascii=False,
                )
            )
        body = "\n".join(lines) + ("\n" if lines else "")
        content_type = "application/x-ndjson"

    elif fmt == "md":
        sections = {}
        for m in qs:
            day = m.ts.strftime("%Y-%m-%d")
            time_str = m.ts.strftime("%H:%M")
            entry = f"### {time_str} · {m.sender}\n{m.content}"
            atts = _attachments(m)
            if atts:
                for a in atts:
                    url = a if isinstance(a, str) else a.get("url", str(a))
                    entry += f"\n[attachment]({url})"
            sections.setdefault(day, []).append(entry)
        parts = []
        for day in sorted(sections):
            parts.append(f"## {day}\n")
            parts.extend(sections[day])
            parts.append("")
        body = "\n".join(parts)
        content_type = "text/markdown; charset=utf-8"

    else:  # txt
        lines = []
        for m in qs:
            ts_str = m.ts.strftime("%Y-%m-%d %H:%M")
            line = f"[{ts_str}] {m.sender}: {m.content}"
            atts = _attachments(m)
            if atts:
                for a in atts:
                    url = a if isinstance(a, str) else a.get("url", str(a))
                    line += f" <{url}>"
            lines.append(line)
        body = "\n".join(lines) + ("\n" if lines else "")
        content_type = "text/plain; charset=utf-8"

    # --- build filename for Content-Disposition ---
    safe_name = channel_name.lstrip("#").replace("/", "-")
    date_tag = (from_dt or datetime.now(dt_timezone.utc)).strftime("%Y-%m-%d")
    filename = f"{safe_name}_{date_tag}.{fmt}"

    from django.http import HttpResponse

    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_GET
def api_media(request):
    """GET /api/media/ — list all file attachments from message metadata.

    Returns newest-first, with sender, timestamp, channel, and attachment info.
    """
    workspace = get_workspace(request)
    limit = min(int(request.GET.get("limit", "200")), 1000)
    offset = max(int(request.GET.get("offset", "0")), 0)

    # Narrow the SQL to messages that actually carry attachments. Prior
    # orochi_version used ``.exclude(metadata={})`` which also matched messages
    # whose metadata only held reactions/replies/mentions — on a busy
    # workspace those crowd out the newest ``limit`` window and the
    # Files tab ends up showing ~1 attachment even when hundreds exist
    # further back in history.
    msgs = (
        Message.objects.filter(workspace=workspace)
        .filter(metadata__has_key="attachments")
        .select_related("channel")
        .order_by("-ts")[offset : offset + limit]
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

    return JsonResponse(items, safe=False)
