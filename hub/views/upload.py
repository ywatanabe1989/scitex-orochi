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

    dest_dir = Path(settings.MEDIA_ROOT) / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{file_id}{ext}"
    dest_file.write_bytes(data)

    # Build the URL defensively — settings.MEDIA_URL may or may not have
    # leading/trailing slashes. Always emit exactly one leading slash and
    # exactly one separator slash so we never produce // (protocol-relative
    # URL) or //media (the bug that broke ywatanabe's image paste).
    media_prefix = "/" + settings.MEDIA_URL.strip("/") + "/"
    url = f"{media_prefix}{subdir}/{file_id}{ext}"
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

    status_code = 200 if result.get("deduplicated") else 201
    return JsonResponse(result, status=status_code)


@csrf_exempt
@_login_or_token_required
def api_media_by_hash(request, content_hash: str):
    """GET /api/media/by-hash/<sha256> — check if content already uploaded.

    Returns 200 + metadata if the hash is known, 404 otherwise.
    HEAD requests can be used for existence checks without downloading metadata.
    """
    if request.method not in ("GET", "HEAD"):
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

    return JsonResponse({**existing, "content_hash": content_hash}, status=200)
