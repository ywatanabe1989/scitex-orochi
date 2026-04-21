"""Test package for the Orochi hub Django app.

Tests are organized to mirror the source-package layout:

  - hub/tests/registry/      — mirrors hub/registry/
  - hub/tests/consumers/     — mirrors hub/consumers/
  - hub/tests/models/        — mirrors hub/models/
  - hub/tests/views/api/     — mirrors hub/views/api/

Cross-cutting test modules (login flow, dotfiles helper) stay at the
top level. Django's default test discovery walks the sub-packages.
"""

# Top-level cross-cutting tests
# Mirror-package tests
from hub.tests.consumers.test_agent_subscription import *  # noqa: F401,F403
from hub.tests.consumers.test_dm import *  # noqa: F401,F403
from hub.tests.consumers.test_mentions import *  # noqa: F401,F403
from hub.tests.consumers.test_reexports import *  # noqa: F401,F403
from hub.tests.models.test_dm_schema import *  # noqa: F401,F403
from hub.tests.models.test_identity import *  # noqa: F401,F403
from hub.tests.models.test_messaging import *  # noqa: F401,F403
from hub.tests.models.test_reexports import *  # noqa: F401,F403
from hub.tests.registry.test_active_sessions import *  # noqa: F401,F403
from hub.tests.registry.test_canonical_metadata import *  # noqa: F401,F403
from hub.tests.registry.test_echo_indicator import *  # noqa: F401,F403
from hub.tests.registry.test_heartbeat import *  # noqa: F401,F403
from hub.tests.registry.test_reexports import *  # noqa: F401,F403
from hub.tests.test_auth import *  # noqa: F401,F403
from hub.tests.test_oauth_helper import *  # noqa: F401,F403
from hub.tests.views.api.test_agent_detail import *  # noqa: F401,F403
from hub.tests.views.api.test_agents_register import *  # noqa: F401,F403
from hub.tests.views.api.test_channel_members import *  # noqa: F401,F403
from hub.tests.views.api.test_channel_members_token import *  # noqa: F401,F403
from hub.tests.views.api.test_channel_rename import *  # noqa: F401,F403
from hub.tests.views.api.test_dms import *  # noqa: F401,F403
from hub.tests.views.api.test_messages import *  # noqa: F401,F403
from hub.tests.views.api.test_my_subscriptions import *  # noqa: F401,F403
from hub.tests.views.api.test_push import *  # noqa: F401,F403
from hub.tests.views.api.test_reexports import *  # noqa: F401,F403
