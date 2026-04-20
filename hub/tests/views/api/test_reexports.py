"""Smoke tests for hub.views.api public re-export surface.

After the api.py → api/ package split, every name in
``hub.views.api.__all__`` must still resolve to a non-None object so
that pre-split callers (``from hub.views import api`` →
``api.api_messages``) keep working unchanged, and every ``api_*``
view must still be callable for hub/urls.py to dispatch to it.
"""

from django.test import SimpleTestCase

import hub.views.api as api


class ApiReExportsTest(SimpleTestCase):
    def test_all_listed(self):
        self.assertTrue(hasattr(api, "__all__"))
        self.assertGreater(len(api.__all__), 0)

    def test_every_listed_name_resolves(self):
        for name in api.__all__:
            self.assertTrue(hasattr(api, name), f"missing: {name}")
            self.assertIsNotNone(getattr(api, name), f"None re-export: {name}")


class ApiViewsCallableTest(SimpleTestCase):
    def test_every_api_view_is_callable(self):
        for name in api.__all__:
            if name.startswith("api_"):
                obj = getattr(api, name)
                self.assertTrue(callable(obj), f"{name} not callable")
