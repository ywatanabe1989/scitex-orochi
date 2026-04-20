"""Smoke tests for hub.consumers public re-export surface.

After the consumers.py → consumers/ package split, every name in
``hub.consumers.__all__`` must still resolve to a non-None object so
that pre-split callers (``from hub.consumers import X``) keep working,
and the consumer classes referenced from hub/routing.py must still
extend ``AsyncJsonWebsocketConsumer``.
"""

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.test import SimpleTestCase

import hub.consumers as consumers


class ConsumersReExportsTest(SimpleTestCase):
    def test_all_listed(self):
        self.assertTrue(hasattr(consumers, "__all__"))
        self.assertGreater(len(consumers.__all__), 0)

    def test_every_listed_name_resolves(self):
        for name in consumers.__all__:
            self.assertTrue(hasattr(consumers, name), f"missing: {name}")
            self.assertIsNotNone(getattr(consumers, name), f"None re-export: {name}")


class ConsumerClassesAreWebsocketConsumersTest(SimpleTestCase):
    def test_consumer_classes_present(self):
        from hub.consumers import AgentConsumer, DashboardConsumer

        self.assertTrue(issubclass(AgentConsumer, AsyncJsonWebsocketConsumer))
        self.assertTrue(issubclass(DashboardConsumer, AsyncJsonWebsocketConsumer))
