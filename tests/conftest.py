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


@pytest.fixture(scope="session")
def llm_judge_available() -> bool:
    """Session-scoped flag indicating whether an LLM judge can be used."""
    return _has_llm_judge_credentials()


def pytest_collection_modifyitems(config, items):
    """Auto-skip ``llm_eval`` tests when no judge credentials are present."""
    if _has_llm_judge_credentials():
        return
    skip_marker = pytest.mark.skip(
        reason=(
            "DeepEval LLM judge tests require an OPENAI_API_KEY, "
            "ANTHROPIC_API_KEY, or DEEPEVAL_API_KEY environment variable."
        )
    )
    for item in items:
        if "llm_eval" in item.keywords:
            item.add_marker(skip_marker)
