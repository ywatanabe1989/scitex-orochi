"""Hub views package — re-exports all view functions."""

from hub.views.api import (  # noqa: F401
    api_agents,
    api_agents_purge,
    api_agents_registry,
    api_channels,
    api_config,
    api_history,
    api_messages,
    api_resources,
    api_stats,
    api_workspaces,
)
from hub.views.auth import (  # noqa: F401
    accept_invite_view,
    create_workspace_view,
    index,
    signin_view,
    signout_view,
    signup_view,
)
from hub.views.github import github_issues  # noqa: F401
from hub.views.landing import (  # noqa: F401
    find_workspace_view,
    landing_page,
    redirect_old_workspace_url,
)
from hub.views.upload import api_upload, api_upload_base64  # noqa: F401
from hub.views.workspace import (  # noqa: F401
    workspace_dashboard,
    workspace_settings_view,
)
