"""Shared pytest fixtures for scitex-orochi tests.

Includes helpers for DeepEval-based LLM-as-judge tests. Tests that need a
real LLM judge should be marked with ``@pytest.mark.llm_eval`` and will be
skipped automatically when no provider API key is configured.
"""

from __future__ import annotations

import os

import pytest


def _has_llm_judge_credentials() -> bool:
    """Return True when at least one LLM provider API key is available."""
    return any(
        os.environ.get(var)
        for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPEVAL_API_KEY")
    )


def _has_deepeval_installed() -> bool:
    """Return True when the ``deepeval`` package is importable."""
    import importlib.util

    return importlib.util.find_spec("deepeval") is not None


@pytest.fixture(scope="session")
def llm_judge_available() -> bool:
    """True only when both an API key *and* the ``deepeval`` package
    are present. Either missing makes the judge unavailable."""
    return _has_llm_judge_credentials() and _has_deepeval_installed()


def pytest_collection_modifyitems(config, items):
    """Auto-skip ``llm_eval`` tests when the judge stack is unavailable.

    Two prerequisites:
      1. An LLM provider API key.
      2. The ``deepeval`` package installed.
    If either is missing the tests are marked skipped with a precise
    reason, so default ``pytest`` invocations stay green in
    environments where DeepEval isn't provisioned (e.g. CI without
    the extra install)."""
    creds = _has_llm_judge_credentials()
    dep = _has_deepeval_installed()
    if creds and dep:
        return
    if not creds:
        reason = (
            "DeepEval LLM judge tests require an OPENAI_API_KEY, "
            "ANTHROPIC_API_KEY, or DEEPEVAL_API_KEY environment variable."
        )
    else:
        reason = (
            "DeepEval LLM judge tests require the 'deepeval' package "
            "(install with 'pip install deepeval')."
        )
    skip_marker = pytest.mark.skip(reason=reason)
    for item in items:
        if "llm_eval" in item.keywords:
            item.add_marker(skip_marker)
