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
from hub.tests.consumers.test_agent_message_echo import *  # noqa: F401,F403
from hub.tests.consumers.test_agent_subs_refresh import *  # noqa: F401,F403
from hub.tests.consumers.test_agent_subscription import *  # noqa: F401,F403
from hub.tests.consumers.test_dm import *  # noqa: F401,F403
from hub.tests.consumers.test_mentions import *  # noqa: F401,F403
from hub.tests.consumers.test_orochi_subagent_count_roundtrip import *  # noqa: F401,F403
from hub.tests.consumers.test_reconnect_resubscribe import *  # noqa: F401,F403
from hub.tests.consumers.test_reexports import *  # noqa: F401,F403
from hub.tests.consumers.test_token_agent_name import *  # noqa: F401,F403
from hub.tests.models.test_channel_membership_bits import *  # noqa: F401,F403
from hub.tests.models.test_dm_schema import *  # noqa: F401,F403
from hub.tests.models.test_identity import *  # noqa: F401,F403
from hub.tests.models.test_messaging import *  # noqa: F401,F403
from hub.tests.models.test_reexports import *  # noqa: F401,F403
from hub.tests.registry.test_active_sessions import *  # noqa: F401,F403
from hub.tests.registry.test_canonical_metadata import *  # noqa: F401,F403
from hub.tests.registry.test_echo_indicator import *  # noqa: F401,F403
from hub.tests.registry.test_heartbeat import *  # noqa: F401,F403
from hub.tests.registry.test_host_identity_from_client import *  # noqa: F401,F403
from hub.tests.registry.test_reexports import *  # noqa: F401,F403
from hub.tests.registry.test_singleton_enforcement import *  # noqa: F401,F403
from hub.tests.api.test_a2a_sdk import *  # noqa: F401,F403
from hub.tests.test_auth import *  # noqa: F401,F403
from hub.tests.test_auto_dispatch import *  # noqa: F401,F403
from hub.tests.test_mention_expansion import *  # noqa: F401,F403
from hub.tests.test_oauth_helper import *  # noqa: F401,F403
from hub.tests.test_observer_tsv_scan import *  # noqa: F401,F403
from hub.tests.test_quota_watch import *  # noqa: F401,F403
from hub.tests.test_scitex_smoke import *  # noqa: F401,F403
from hub.tests.test_singleton_host_check import *  # noqa: F401,F403
from hub.tests.test_worker_progress_seed import *  # noqa: F401,F403
from hub.tests.views.api.test_admin_subscribe import *  # noqa: F401,F403
from hub.tests.views.api.test_agent_detail import *  # noqa: F401,F403
from hub.tests.views.api.test_agents_list_token import *  # noqa: F401,F403
from hub.tests.views.api.test_agents_register import *  # noqa: F401,F403
from hub.tests.views.api.test_auto_dispatch_api import *  # noqa: F401,F403
from hub.tests.views.api.test_channel_members import *  # noqa: F401,F403
from hub.tests.views.api.test_channel_members_token import *  # noqa: F401,F403
from hub.tests.views.api.test_channel_rename import *  # noqa: F401,F403
from hub.tests.views.api.test_connectivity import *  # noqa: F401,F403
from hub.tests.views.api.test_cron import *  # noqa: F401,F403
from hub.tests.views.api.test_dms import *  # noqa: F401,F403
from hub.tests.views.api.test_inbound_email import *  # noqa: F401,F403
from hub.tests.views.api.test_liveness_pane_state import *  # noqa: F401,F403
from hub.tests.views.api.test_messages import *  # noqa: F401,F403
from hub.tests.views.api.test_my_subscriptions import *  # noqa: F401,F403
from hub.tests.views.api.test_push import *  # noqa: F401,F403
from hub.tests.views.api.test_reexports import *  # noqa: F401,F403
from hub.tests.views.api.test_watchdog_alerts import *  # noqa: F401,F403
