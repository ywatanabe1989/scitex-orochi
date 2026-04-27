"""Example agentic test using DeepEval (LLM-as-judge).

This module demonstrates how to evaluate the *behavior* of an Orochi agent
using another LLM as the judge via the DeepEval framework.

Running these tests
-------------------
The tests are marked with ``llm_eval`` and are skipped automatically unless
an LLM provider API key is configured. To run them locally::

    export OPENAI_API_KEY=sk-...
    pytest tests/test_agent_eval.py -v -m llm_eval

To skip them in a normal test run::

    pytest -m "not llm_eval"

Wiring up a real Orochi agent
-----------------------------
Replace :func:`mock_agent` below with a function that sends ``prompt`` to a
real Orochi agent (e.g. via the MCP ``task`` tool or a websocket client) and
returns the agent's textual reply. The rest of the test — metric definition,
threshold, and judge — stays the same.
"""

from __future__ import annotations

import pytest


def mock_agent(prompt: str) -> str:
    """Stand-in for a real Orochi agent.

    Replace this with a real agent call once the test harness is ready.
    """
    return (
        "Hello! I'd be happy to help you with that. "
        "Could you share a few more details so I can give you the best answer?"
    )


@pytest.mark.llm_eval
def test_agent_response_is_polite_and_helpful():
    """The agent's reply must be judged 'polite and helpful' by an LLM."""
    # Imported lazily so the test module can be collected without DeepEval
    # installed (e.g. when running ``pytest -m "not llm_eval"``).
    from deepeval import assert_test
    from deepeval.orochi_metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    prompt = "I'm stuck on a Python import error, can you help?"
    agent_output = mock_agent(prompt)

    politeness_metric = GEval(
        name="PoliteAndHelpful",
        criteria=(
            "Determine whether the assistant's response is both polite "
            "(courteous, respectful tone) and helpful (acknowledges the "
            "user's request and offers concrete next steps or assistance)."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        threshold=0.7,
    )

    test_case = LLMTestCase(input=prompt, actual_output=agent_output)
    assert_test(test_case, [politeness_metric])
