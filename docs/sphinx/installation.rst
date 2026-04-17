Installation
============

From PyPI
---------

.. code-block:: bash

    pip install scitex-orochi

From Source
-----------

.. code-block:: bash

    git clone https://github.com/ywatanabe1989/scitex-orochi.git
    cd scitex-orochi
    pip install -e .

Requirements
------------

- Python >= 3.11
- `Bun <https://bun.sh/>`_ >= 1.0 — only if you use the TypeScript MCP
  channel sidecar (``src/scitex_orochi/_ts/mcp_channel.ts``).
- `scitex-agent-container <https://github.com/ywatanabe1989/scitex-agent-container>`_
  — required on any host that runs ``scitex-orochi heartbeat-push``.
  The hub itself does not need it. scitex-orochi depends on
  scitex-agent-container in one direction only: the container CLI has
  no knowledge of Orochi.
