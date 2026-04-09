"""Upload views for file and base64 (sketch) uploads."""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

log = logging.getLogger(__name__)

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_MIME_PREFIXES = (
    "image/",
    "text/",
    "application/pdf",
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-python",
)


def _is_allowed(mime_type: str) -> bool:
    return any(mime_type.startswith(p) for p in ALLOWED_MIME_PREFIXES)


def _save_to_media(data: bytes, filename: str, mime_type: str) -> dict:
    """Save bytes to MEDIA_ROOT/<YYYY-MM>/<uuid>.<ext>, return metadata."""
    if len(data) > MAX_UPLOAD_SIZE:
        raise ValueError(f"File too large: {len(data)} > {MAX_UPLOAD_SIZE}")

    if not mime_type:
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    if not _is_allowed(mime_type):
        raise ValueError(f"File type not allowed: {mime_type}")

    ext = Path(filename).suffix or mimetypes.guess_extension(mime_type) or ""
    file_id = str(uuid.uuid4())
    subdir = datetime.now(timezone.utc).strftime("%Y-%m")

    dest_dir = Path(settings.MEDIA_ROOT) / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{file_id}{ext}"
    dest_file.write_bytes(data)

    url = f"/{settings.MEDIA_URL}{subdir}/{file_id}{ext}"
    return {
        "file_id": file_id,
        "url": url,
        "mime_type": mime_type,
        "filename": filename,
        "size": len(data),
    }


@login_required
@require_POST
def api_upload(request):
    """POST /api/upload -- multipart file upload."""
    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "No file field"}, status=400)

    data = uploaded.read()
    filename = uploaded.name or "upload"
    mime_type = uploaded.content_type or ""

    try:
        result = _save_to_media(data, filename, mime_type)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=413)

    return JsonResponse(result, status=201)


@login_required
@require_POST
def api_upload_base64(request):
    """POST /api/upload-base64 -- base64-encoded file upload (sketches)."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    b64_data = body.get("data", "")
    filename = body.get("filename", "upload")
    mime_type = body.get("mime_type", "")

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

    return JsonResponse(result, status=201)
