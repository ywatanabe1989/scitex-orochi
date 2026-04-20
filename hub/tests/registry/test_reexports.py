"""Smoke tests for hub.registry public re-export surface.

After the registry.py → registry/ package split, every name in
``hub.registry.__all__`` must still resolve to a non-None object so
that pre-split callers (``from hub.registry import X``) keep working
unchanged.
"""

from django.test import SimpleTestCase

import hub.registry as registry


class RegistryReExportsTest(SimpleTestCase):
    def test_all_listed(self):
        self.assertTrue(hasattr(registry, "__all__"))
        self.assertGreater(len(registry.__all__), 0)

    def test_every_listed_name_resolves(self):
        for name in registry.__all__:
            self.assertTrue(hasattr(registry, name), f"missing: {name}")
            self.assertIsNotNone(getattr(registry, name), f"None re-export: {name}")
