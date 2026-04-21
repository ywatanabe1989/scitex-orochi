"""Hub views package — re-exports all view functions."""

from hub.views.agent_detail import api_agent_detail  # noqa: F401
from hub.views.api import (  # noqa: F401
    api_agent_health,
    api_agent_profiles,
    api_agents,
    api_agents_kill,
    api_agents_pin,
    api_agents_pinned,
    api_agents_purge,
    api_agents_register,
    api_agents_registry,
    api_agents_restart,
    api_channel_export,
    api_channel_members,
    api_channel_prefs,
    api_channels,
    api_config,
    api_connectivity,
    api_dms,
    api_event_tool_use,
    api_history,
    api_media,
    api_members,
    api_message_detail,
    api_messages,
    api_my_subscriptions,
    api_push_subscribe,
    api_push_unsubscribe,
    api_push_vapid_key,
    api_reactions,
    api_releases,
    api_repo_changelog,
    api_resources,
    api_scheduled,
    api_stats,
    api_subagents_update,
    api_threads,
    api_watchdog_alerts,
    api_workspaces,
    fleet_report,
    fleet_state,
)
from hub.views.auth import (  # noqa: F401
    accept_invite_view,
    agent_login_view,
    create_workspace_view,
    index,
    signin_view,
    signout_view,
    signup_view,
)
from hub.views.avatar import api_agents_avatar  # noqa: F401
from hub.views.channels_rename import (  # noqa: F401
    api_channel_rename,
    api_channel_rename_prefix,
)
from hub.views.discover import api_discover  # noqa: F401
from hub.views.github import github_issue_title, github_issues  # noqa: F401
from hub.views.landing import (  # noqa: F401
    find_workspace_view,
    landing_page,
    redirect_old_workspace_url,
    request_invite_view,
)
from hub.views.registry import (  # noqa: F401
    api_registry_agent_detail,
    api_registry_agents,
)
from hub.views.status import api_status, status_page  # noqa: F401
from hub.views.telegram import telegram_webhook  # noqa: F401
from hub.views.tracked_repos import (  # noqa: F401
    api_tracked_repo_detail,
    api_tracked_repos,
    api_tracked_repos_reorder,
)
from hub.views.upload import (  # noqa: F401
    api_media_by_hash,
    api_upload,
    api_upload_base64,
)
from hub.views.user_profile import (  # noqa: F401
    api_user_profile,
    api_user_profile_avatar,
    api_workspace_member_avatars,
)
from hub.views.webhook_github import github_webhook  # noqa: F401
from hub.views.workspace import (  # noqa: F401
    workspace_dashboard,
    workspace_settings_view,
)
from hub.views.workspace_icon import api_workspace_icon  # noqa: F401
