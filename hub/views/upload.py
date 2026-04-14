"""Upload views for file and base64 (sketch) uploads."""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from hub.models import WorkspaceToken

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Content-addressable hash index
# Files live at MEDIA_ROOT/.hashes/<sha[:2]>/<sha>.json
# Each JSON contains {"url": "...", "filename": "...", "size": N, "mime_type": "..."}
# ---------------------------------------------------------------------------

def _hash_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_index_path(content_hash: str) -> Path:
    base = Path(settings.MEDIA_ROOT) / ".hashes" / content_hash[:2]
    return base / f"{content_hash}.json"


def _hash_lookup(content_hash: str) -> dict | None:
    """Return existing metadata if this hash was already uploaded, else None."""
    p = _hash_index_path(content_hash)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return None


def _hash_store(content_hash: str, metadata: dict) -> None:
    """Persist hash→metadata mapping atomically."""
    p = _hash_index_path(content_hash)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write via rename (temp file in same dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(metadata))
    tmp.replace(p)

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB (was 10 MB; bumped 2026-04-12 for fleet PDF/dataset sharing)


def _login_or_token_required(view_func):
    """Allow access via Django session OR workspace token query param."""

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user and request.user.is_authenticated:
            return view_func(request, *args, **kwargs)
        token = request.GET.get("token") or request.POST.get("token")
        if token:
            try:
                WorkspaceToken.objects.get(token=token)
                return view_func(request, *args, **kwargs)
            except WorkspaceToken.DoesNotExist:
                pass
        return JsonResponse({"error": "Authentication required"}, status=401)

    return wrapper

ALLOWED_MIME_PREFIXES = (
    "image/",
    "text/",
    "application/pdf",
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-python",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/octet-stream",
    "application/vnd.openxmlformats",
    "application/vnd.ms-",
    "audio/",
    "video/",
)


def _is_allowed(mime_type: str) -> bool:
    return any(mime_type.startswith(p) for p in ALLOWED_MIME_PREFIXES)


def _save_to_media(data: bytes, filename: str, mime_type: str, dedupe: bool = True) -> dict:
    """Save bytes to MEDIA_ROOT/<YYYY-MM>/<uuid>.<ext>, return metadata.

    If dedupe=True (default), checks the content-hash index first and returns
    the existing media reference if this exact file was already uploaded.
    The response includes 'deduplicated': True when reusing an existing blob.
    """
    if len(data) > MAX_UPLOAD_SIZE:
        raise ValueError(f"File too large: {len(data)} > {MAX_UPLOAD_SIZE}")

    if not mime_type:
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    if not _is_allowed(mime_type):
        raise ValueError(f"File type not allowed: {mime_type}")

    # --- Content-addressable dedup ---
    content_hash = _hash_of(data)
    if dedupe:
        existing = _hash_lookup(content_hash)
        if existing:
            log.debug("[upload] dedup hit: %s -> %s", content_hash[:12], existing.get("url"))
            return {**existing, "deduplicated": True, "content_hash": content_hash}

    ext = Path(filename).suffix or mimetypes.guess_extension(mime_type) or ""
    file_id = str(uuid.uuid4())
    subdir = datetime.now(timezone.utc).strftime("%Y-%m")
    # Store as <subdir>/<uuid>/<original-filename> so the URL path ends with
    # the clean original filename — the browser uses the last path component
    # as the default save name, no Content-Disposition header needed (#397).
    import re as _re
    safe_stem = _re.sub(r'[^\w\-.]', '_', Path(filename).stem)[:80]
    safe_name = f"{safe_stem}{ext}" if safe_stem else f"upload{ext}"
    dest_dir = Path(settings.MEDIA_ROOT) / subdir / file_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / safe_name
    # Timestamp suffix if collision (shouldn't happen with UUID dir, but safe)
    if dest_file.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        dest_file = dest_dir / f"{safe_stem}_{ts}{ext}"
    dest_file.write_bytes(data)

    # Build the URL defensively — settings.MEDIA_URL may or may not have
    # leading/trailing slashes. Always emit exactly one leading slash and
    # exactly one separator slash so we never produce // (protocol-relative
    # URL) or //media (the bug that broke ywatanabe's image paste).
    media_prefix = "/" + settings.MEDIA_URL.strip("/") + "/"
    url = f"{media_prefix}{subdir}/{file_id}/{dest_file.name}"
    metadata = {
        "file_id": file_id,
        "url": url,
        "mime_type": mime_type,
        "filename": filename,
        "size": len(data),
        "content_hash": content_hash,
        "deduplicated": False,
    }
    _hash_store(content_hash, metadata)
    return metadata


@csrf_exempt
@_login_or_token_required
@require_POST
def api_upload(request):
    """POST /api/upload -- multipart file upload.

    Accepts ONE or MANY files. Multiple files can be sent in a single
    request as repeated `file` form fields. Returns a JSON object with
    a `files` array (multiple) AND mirrors the first file's fields at
    the top level for backward compatibility with single-file callers.
    """
    uploads = request.FILES.getlist("file")
    if not uploads:
        return JsonResponse({"error": "No file field"}, status=400)

    results = []
    errors = []
    for uploaded in uploads:
        try:
            data = uploaded.read()
            filename = uploaded.name or "upload"
            mime_type = uploaded.content_type or ""
            results.append(_save_to_media(data, filename, mime_type))
        except ValueError as exc:
            errors.append({"filename": uploaded.name, "error": str(exc)})

    if not results and errors:
        return JsonResponse({"errors": errors}, status=413)

    response = {
        "files": results,
        "errors": errors,
        "count": len(results),
    }
    if results:
        # Mirror first file's fields at top level for backward compat
        # (older clients expect file_id, url, mime_type, filename, size).
        response.update(results[0])
    return JsonResponse(response, status=201)


@csrf_exempt
@_login_or_token_required
@require_POST
def api_upload_base64(request):
    """POST /api/upload-base64 -- base64-encoded file upload.

    Body: {
        "data": "<base64>",
        "filename": "foo.md",
        "mime_type": "text/markdown",  # optional, sniffed from filename if absent
        "channel": "#ywatanabe",        # optional — when present, also creates a
                                        #   Message row with attachments=[file]
                                        #   so the file shows in the Files tab.
                                        #   Without this, the file lands on disk
                                        #   but is invisible to api_media which
                                        #   only reads Message.metadata.attachments.
        "sender": "agent-name",         # optional — sender for the auto-message
                                        #   when channel is set; falls back to
                                        #   the workspace token's owner.
    }

    Response: file metadata dict; if a message was created, response also
    includes "message_id".
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    b64_data = body.get("data", "")
    filename = body.get("filename", "upload")
    mime_type = body.get("mime_type", "")
    channel_name = (body.get("channel") or "").strip()
    sender_name = (body.get("sender") or "").strip()

    if not b64_data:
        return JsonResponse({"error": "No data field"}, status=400)

    try:
        data = base64.b64decode(b64_data)
    except Exception:
        return JsonResponse({"error": "Invalid base64"}, status=400)

    try:
        result = _save_to_media(data, filename, mime_type)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=413)

    # If the caller passed a channel, persist a Message row carrying this
    # file as an attachment so the Files tab (api_media) and the channel
    # feed both see the upload. Without this, agents using upload_media
    # alone produce orphaned blobs that never appear in the dashboard.
    if channel_name:
        try:
            from hub.models import Channel, Message
            from hub.views._helpers import get_workspace
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            workspace = get_workspace(request)
            ch, _ = Channel.objects.get_or_create(
                workspace=workspace, name=channel_name
            )
            sender = sender_name or (
                request.user.username
                if getattr(request, "user", None)
                and request.user.is_authenticated
                else "agent"
            )
            sender_type = (
                "human"
                if getattr(request, "user", None)
                and request.user.is_authenticated
                else "agent"
            )
            attachment_meta = {
                "url": result.get("url"),
                "filename": result.get("filename"),
                "mime_type": result.get("mime_type"),
                "size": result.get("size"),
                "file_id": result.get("file_id"),
            }
            msg = Message.objects.create(
                workspace=workspace,
                channel=ch,
                sender=sender,
                sender_type=sender_type,
                content="",
                metadata={"attachments": [attachment_meta]},
            )
            result["message_id"] = msg.id
            # Broadcast to live dashboard listeners.
            try:
                layer = get_channel_layer()
                if layer is not None:
                    async_to_sync(layer.group_send)(
                        f"workspace_{workspace.id}",
                        {
                            "type": "chat.message",
                            "id": msg.id,
                            "sender": sender,
                            "sender_type": sender_type,
                            "channel": channel_name,
                            "text": "",
                            "ts": msg.ts.isoformat(),
                            "metadata": {"attachments": [attachment_meta]},
                        },
                    )
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001 — never block the upload
            log.warning(
                "[upload] auto-message creation failed for %s: %s",
                filename,
                exc,
            )

    status_code = 200 if result.get("deduplicated") else 201
    return JsonResponse(result, status=status_code)


@csrf_exempt
@_login_or_token_required
def api_media_by_hash(request, content_hash: str):
    """``/api/media/by-hash/<sha256>`` — content-addressable media probe + attach.

    GET / HEAD
        Existence check. Returns 200 + metadata if the hash is known, 404
        otherwise. HEAD returns no body.

    POST  (todo#97)
        Attach an existing blob to a channel without re-uploading. Body::

            { "channel": "#name", "sender": "agent-name" (optional) }

        On success the server creates a ``Message`` row whose
        ``metadata.attachments[0]`` references the existing blob, then
        broadcasts the message to live dashboard listeners. This closes
        the dedup-orphan bug where ``upload_media`` standalone returned
        the existing URL but never produced a Message row, leaving the
        file invisible in the Files tab.

    All variants validate the hash format up front so injection probes
    can't reach the filesystem layer.
    """
    if request.method not in ("GET", "HEAD", "POST"):
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # Validate hash is plausible (64 hex chars for sha256)
    if len(content_hash) != 64 or not all(c in "0123456789abcdef" for c in content_hash.lower()):
        return JsonResponse({"error": "Invalid hash format (expected sha256 hex)"}, status=400)

    existing = _hash_lookup(content_hash)
    if existing is None:
        return JsonResponse({"error": "Not found"}, status=404)

    if request.method == "HEAD":
        from django.http import HttpResponse
        r = HttpResponse(status=200)
        r["X-Content-Hash"] = content_hash
        return r

    if request.method == "GET":
        return JsonResponse({**existing, "content_hash": content_hash}, status=200)

    # ---- POST: attach existing blob to a channel as a Message row ----
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    channel_name = (body.get("channel") or "").strip()
    if not channel_name:
        return JsonResponse(
            {"error": "channel field required for POST attach"}, status=400
        )
    sender_name = (body.get("sender") or "").strip()

    # Normalize channel names to match the #326 write-path convention so
    # the attach-by-hash endpoint never creates a duplicate bare-name row.
    if not channel_name.startswith("dm:") and not channel_name.startswith("#"):
        channel_name = "#" + channel_name

    try:
        from hub.models import Channel, Message
        from hub.views._helpers import get_workspace
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        workspace = get_workspace(request)
        ch, _ = Channel.objects.get_or_create(
            workspace=workspace, name=channel_name
        )

        is_authed_user = (
            getattr(request, "user", None) is not None
            and request.user.is_authenticated
        )
        sender = sender_name or (
            request.user.username if is_authed_user else "agent"
        )
        sender_type = "human" if is_authed_user else "agent"

        attachment_meta = {
            "url": existing.get("url"),
            "filename": existing.get("filename"),
            "mime_type": existing.get("mime_type"),
            "size": existing.get("size"),
            "file_id": existing.get("file_id"),
            "content_hash": content_hash,
        }
        msg = Message.objects.create(
            workspace=workspace,
            channel=ch,
            sender=sender,
            sender_type=sender_type,
            content="",
            metadata={"attachments": [attachment_meta]},
        )

        # Broadcast to live dashboard listeners (best-effort).
        try:
            layer = get_channel_layer()
            if layer is not None:
                async_to_sync(layer.group_send)(
                    f"workspace_{workspace.id}",
                    {
                        "type": "chat.message",
                        "id": msg.id,
                        "sender": sender,
                        "sender_type": sender_type,
                        "channel": channel_name,
                        "text": "",
                        "ts": msg.ts.isoformat(),
                        "metadata": {"attachments": [attachment_meta]},
                    },
                )
        except Exception:
            log.warning(
                "[attach-by-hash] live broadcast failed for %s",
                content_hash[:12],
            )

        return JsonResponse(
            {
                **existing,
                "content_hash": content_hash,
                "deduplicated": True,
                "message_id": msg.id,
                "channel": channel_name,
            },
            status=201,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("[attach-by-hash] failed for %s", content_hash[:12])
        return JsonResponse(
            {"error": f"attach failed: {exc}"}, status=500
        )
