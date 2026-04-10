"""Telegram webhook receiver — POST /webhook/telegram"""

import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from hub.models import Channel, Message, Workspace

log = logging.getLogger("orochi.telegram")


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Receive a Telegram Update via webhook and broadcast to #telegram channel."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    msg = data.get("message") or {}
    from_user = msg.get("from", {})
    text = msg.get("text") or msg.get("caption") or ""
    chat_id = str(msg.get("chat", {}).get("id", ""))
    user_id = str(from_user.get("id", ""))
    username = from_user.get("username") or from_user.get("first_name") or user_id
    message_id = str(msg.get("message_id", ""))

    if not text and not msg:
        return HttpResponse("ok", status=200)

    metadata = {
        "source": "telegram",
        "telegram_chat_id": chat_id,
        "telegram_message_id": message_id,
        "telegram_user_id": user_id,
        "telegram_username": username,
    }
    sender = f"telegram:{username}"
    ch_name = "#telegram"

    # Persist message and broadcast via channel layer
    workspace = Workspace.objects.first()
    if workspace:
        channel, _ = Channel.objects.get_or_create(workspace=workspace, name=ch_name)
        saved = Message.objects.create(
            workspace=workspace,
            channel=channel,
            sender=sender,
            sender_type="human",
            content=text,
            metadata=metadata,
        )

        channel_layer = get_channel_layer()
        if channel_layer:
            group_name = f"workspace_{workspace.id}"
            orochi_msg = {
                "type": "chat.message",
                "id": saved.id,
                "sender": sender,
                "sender_type": "human",
                "channel": ch_name,
                "text": text,
                "ts": saved.ts.isoformat(),
                "metadata": metadata,
            }
            async_to_sync(channel_layer.group_send)(group_name, orochi_msg)

        log.info("Telegram webhook: %s: %s", username, text[:50])

    return HttpResponse("ok", status=200)
