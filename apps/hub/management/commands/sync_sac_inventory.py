"""Management command — sac inventory reconciler daemon (ADR-0003 Phase 1).

Wraps the async ``run()`` loop in
``scitex_orochi._daemons._sac_inventory_sync`` so the daemon can be
launched as a long-running supervised process via::

    python manage.py sync_sac_inventory

See the module docstring of ``_sac_inventory_sync`` for behaviour and
deferred scope.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Run the sac inventory reconciler daemon. Reconciles "
        "AgentProfile rows against ~/.scitex/agent-container/agents/*/"
        "spec.yaml every SCITEX_OROCHI_SAC_SYNC_INTERVAL seconds "
        "(default 300). ADR-0003 Phase 1."
    )

    def handle(self, *args, **options):
        # Lazy import — keep Django's management-command boot path
        # from triggering the daemon module's logger setup until we
        # actually intend to run.
        from scitex_orochi._daemons._sac_inventory_sync import main

        return main()
