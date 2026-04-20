"""Smoke tests for hub.models public re-export surface.

After the models.py → models/ package split, every name in
``hub.models.__all__`` must still resolve to a non-None object so
that pre-split callers (``from hub.models import X``) keep working,
and every re-exported class must be either a Django ``Model`` subclass
or a callable helper (e.g. ``normalize_channel_name``).
"""

from django.db.models import Model
from django.test import SimpleTestCase

import hub.models as m


class ModelsReExportsTest(SimpleTestCase):
    def test_all_listed(self):
        self.assertTrue(hasattr(m, "__all__"))
        self.assertGreater(len(m.__all__), 0)

    def test_every_listed_name_resolves(self):
        for name in m.__all__:
            self.assertTrue(hasattr(m, name), f"missing: {name}")
            self.assertIsNotNone(getattr(m, name), f"None re-export: {name}")


class ModelsAreDjangoModelsTest(SimpleTestCase):
    def test_each_re_export_is_a_django_model_or_callable(self):
        for name in m.__all__:
            obj = getattr(m, name)
            is_model = isinstance(obj, type) and issubclass(obj, Model)
            self.assertTrue(
                is_model or callable(obj),
                f"{name} is neither a Django Model nor a callable helper",
            )
