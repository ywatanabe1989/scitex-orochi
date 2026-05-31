"""Auto-generated smoke test for the skills-quality checker.

Replaces the prior placeholder-only stub (audit-project PS206). The
test imports the target module — if the import fails, the test
fails. Renames, broken peer deps, or missing optional deps all
surface here as red, not as a silent skip.

The skills-quality checks for scitex-orochi live in the shared
``scitex_dev._skills_quality_pytest`` helper (there is no
``scitex_orochi.skills_quality`` module); import that instead.

If a module legitimately requires an optional dep, that dep should
be lazy-imported inside the function bodies — not at module top.
"""

import importlib


def test_module_imports():
    """Smoke: target module imports without error."""
    importlib.import_module('scitex_dev._skills_quality_pytest')
