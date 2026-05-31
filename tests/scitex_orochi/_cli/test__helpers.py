"""Mirror test for ``src/scitex_orochi/_cli/_helpers.py``.

Dependency-free structural surface check: parses the source file with
``ast`` (no import of optional runtime deps such as websockets/fastmcp)
and asserts the module's public API surface exists. The source file is
located relative to this test file so the check works in any checkout.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SRC = _REPO / "src" / "scitex_orochi" / '_cli' / '_helpers.py'


def test_helpers_surface():
    # Arrange
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    # Act
    funcs = {
        n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    # Assert
    assert "make_client" in funcs
