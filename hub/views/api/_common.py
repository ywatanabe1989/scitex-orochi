"""Shared imports, helpers, and module-level constants for the api package.

Every domain module re-imports symbols from here so the cut/paste split
of the original ``hub/views/api.py`` keeps a single canonical place
for the cross-cutting state (``_server_start_time``, ``log``) and for
the stdlib / Django / hub imports that nearly every endpoint uses.
"""

import json
import logging
import os
import platform
import time
from datetime import datetime
from datetime import timezone as dt_timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from hub.channel_acl import check_write_allowed
from hub.models import (
    Channel,
    ChannelPreference,
    DMParticipant,
    FleetReport,
    Message,
    MessageReaction,
    MessageThread,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
    normalize_channel_name,
)
from hub.views._helpers import get_workspace

_server_start_time = time.time()

log = logging.getLogger("orochi.api")

__all__ = [
    "Channel",
    "ChannelPreference",
    "DMParticipant",
    "FleetReport",
    "JsonResponse",
    "Message",
    "MessageReaction",
    "MessageThread",
    "Workspace",
    "WorkspaceMember",
    "WorkspaceToken",
    "_server_start_time",
    "async_to_sync",
    "check_write_allowed",
    "csrf_exempt",
    "datetime",
    "dt_timezone",
    "get_channel_layer",
    "get_workspace",
    "json",
    "log",
    "login_required",
    "normalize_channel_name",
    "os",
    "platform",
    "require_GET",
    "require_http_methods",
    "settings",
    "time",
    "timezone",
]
