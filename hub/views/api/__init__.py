"""REST API views for workspace data.

This package was split out of the 3000+-line ``hub/views/api.py`` monolith
into focused sub-modules. The public surface — every ``api_*`` view
callable that ``hub/urls.py`` and ``hub/views/__init__.py`` import — is
re-exported here so ``from hub.views import api`` and
``api.api_messages`` keep working unchanged.

The ``_ensure_dm_channel`` helper is also re-exported because
``hub/consumers/_agent_message.py`` and ``_dashboard_message.py`` import
it directly from ``hub.views.api`` to share the DM lazy-creation logic
with the REST write path.
"""

from hub.views.api._a2a_dispatch import api_a2a_reply
from hub.views.api._agents import (
    api_agent_health,
    api_agent_profiles,
    api_agents,
    api_agents_pin,
    api_agents_pinned,
    api_agents_purge,
    api_agents_registry,
    api_subagents_update,
)
from hub.views.api._agents_lifecycle import api_agents_kill, api_agents_restart
from hub.views.api._agents_register import api_agents_register
from hub.views.api._agents_subscribe import (
    api_admin_agent_subscribe,
    api_admin_agent_unsubscribe,
)
from hub.views.api._auto_dispatch import (
    api_auto_dispatch_fire,
    api_auto_dispatch_status,
)
from hub.views.api._channels import (
    api_channel_members,
    api_channel_prefs,
    api_channels,
    api_my_subscriptions,
    api_stats,
    api_workspaces,
)
from hub.views.api._cron import api_cron
from hub.views.api._dms import _ensure_dm_channel, api_dms
from hub.views.api._export import api_channel_export, api_media
from hub.views.api._fleet import api_scheduled, fleet_report, fleet_state
from hub.views.api._inbound_email import api_inbound_email, route_email  # noqa: F401
from hub.views.api._messages import api_history, api_messages, api_threads
from hub.views.api._misc import (
    api_config,
    api_connectivity,
    api_event_tool_use,
    api_members,
    api_push_subscribe,
    api_push_unsubscribe,
    api_push_vapid_key,
    api_watchdog_alerts,
)
from hub.views.api._reactions import api_message_detail, api_reactions
from hub.views.api._releases import api_releases, api_repo_changelog
from hub.views.api._resources import api_resources

__all__ = [
    "_ensure_dm_channel",
    "api_a2a_reply",
    "api_agent_health",
    "api_agent_profiles",
    "api_agents",
    "api_agents_kill",
    "api_agents_pin",
    "api_agents_pinned",
    "api_agents_purge",
    "api_admin_agent_subscribe",
    "api_admin_agent_unsubscribe",
    "api_agents_register",
    "api_agents_registry",
    "api_agents_restart",
    "api_auto_dispatch_fire",
    "api_auto_dispatch_status",
    "api_channel_export",
    "api_channel_members",
    "api_channel_prefs",
    "api_channels",
    "api_config",
    "api_connectivity",
    "api_cron",
    "api_inbound_email",
    "api_dms",
    "api_event_tool_use",
    "api_history",
    "api_media",
    "api_members",
    "api_message_detail",
    "api_messages",
    "api_my_subscriptions",
    "api_push_subscribe",
    "api_push_unsubscribe",
    "api_push_vapid_key",
    "api_reactions",
    "api_releases",
    "api_repo_changelog",
    "api_resources",
    "api_scheduled",
    "api_stats",
    "api_subagents_update",
    "api_threads",
    "api_watchdog_alerts",
    "api_workspaces",
    "fleet_report",
    "fleet_state",
]
