"""Hub views package — re-exports all view functions."""

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
    api_channels,
    api_config,
    api_connectivity,
    api_event_tool_use,
    api_history,
    api_media,
    api_members,
    api_message_detail,
    api_messages,
    api_reactions,
    api_releases,
    api_repo_changelog,
    api_resources,
    api_stats,
    api_subagents_update,
    api_threads,
    api_watchdog_alerts,
    api_workspaces,
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
from hub.views.discover import api_discover  # noqa: F401
from hub.views.github import github_issue_title, github_issues  # noqa: F401
from hub.views.landing import (  # noqa: F401
    find_workspace_view,
    landing_page,
    redirect_old_workspace_url,
)
from hub.views.telegram import telegram_webhook  # noqa: F401
from hub.views.webhook_github import github_webhook  # noqa: F401
from hub.views.upload import api_upload, api_upload_base64  # noqa: F401
from hub.views.workspace import (  # noqa: F401
    workspace_dashboard,
    workspace_settings_view,
)
