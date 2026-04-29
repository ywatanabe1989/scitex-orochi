"""On-demand message translation via Claude API (todo#409 Phase 1).

POST /api/messages/<id>/translate/
Body: {"target_lang": "en"}  (default: "en")
Returns: {"translated_text": "...", "source_lang": "auto", "target_lang": "en"}

Uses ANTHROPIC_API_KEY.  Returns 503 if the key is absent.
Does NOT cache — translations are on-demand and ephemeral for Phase 1.
"""

from __future__ import annotations

import json
import os

import httpx
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hub.models import Message, WorkspaceToken
from hub.views.api._channels import get_workspace

_ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
_TRANSLATE_MODEL = "claude-haiku-4-5-20251001"


@csrf_exempt
@require_http_methods(["POST"])
def api_message_translate(request, message_id):
    """POST /api/messages/<id>/translate/ — translate a single message."""
    # Auth — token or session (checked before API key to avoid leaking config)
    token_str = request.GET.get("token") or request.POST.get("token")
    if token_str:
        try:
            wks_token = WorkspaceToken.objects.select_related("workspace").get(token=token_str)
            workspace = wks_token.workspace
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "invalid token"}, status=401)
    elif request.user and request.user.is_authenticated:
        workspace = get_workspace(request)
    else:
        return JsonResponse({"error": "auth required"}, status=401)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JsonResponse({"error": "translation unavailable (no API key)"}, status=503)

    try:
        msg = Message.objects.get(id=message_id, workspace=workspace, deleted_at__isnull=True)
    except Message.DoesNotExist:
        return JsonResponse({"error": "message not found"}, status=404)

    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)

    target_lang = body.get("target_lang", "en").strip()[:10]  # cap length
    original_text = msg.content

    prompt = (
        f"Translate the following text to {target_lang}. "
        "Return only the translated text with no explanation. "
        "Preserve technical terms, code blocks (```...```), URLs, "
        "filenames, and proper nouns exactly as written.\n\n"
        f"{original_text}"
    )

    try:
        resp = httpx.post(
            _ANTHROPIC_API,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _TRANSLATE_MODEL,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        translated = data["content"][0]["text"].strip()
    except httpx.HTTPStatusError as e:
        return JsonResponse({"error": f"translation API error: {e.response.status_code}"}, status=502)
    except (httpx.RequestError, KeyError, IndexError, ValueError) as e:
        return JsonResponse({"error": f"translation failed: {type(e).__name__}"}, status=502)

    return JsonResponse({
        "translated_text": translated,
        "original_text": original_text,
        "target_lang": target_lang,
        "source_lang": "auto",
    })
