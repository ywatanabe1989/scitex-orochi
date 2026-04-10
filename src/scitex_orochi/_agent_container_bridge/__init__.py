"""Bridge between scitex-orochi and scitex-agent-container.

This subpackage owns ALL Orochi-specific plumbing that used to live inside
scitex-agent-container. scitex-agent-container is now a pure generic agent
lifecycle library; scitex-orochi uses it as a consumer, preprocessing the
yaml (to extract the ``spec.orochi:`` section), generating the MCP config
file, resolving the workspace token, and injecting ``--mcp-config`` /
``--dangerously-load-development-channels`` flags into a shim yaml before
calling ``agent_start``.

Public API:
  - ``OrochiSpec`` — dataclass for ``spec.orochi:``
  - ``load_orochi_spec(yaml_path)`` — parse the section from a file
  - ``build_orochi_mcp_config(...)`` — produce the MCP json config
  - ``write_mcp_config_file(...)`` — write it to disk and return the path
  - ``start_orochi_sidecar(...)`` — launch the websocket sidecar thread
  - ``resolve_orochi_token(spec)`` — resolve the workspace token
"""

from .connector import resolve_orochi_token, start_orochi_sidecar
from .mcp import build_orochi_mcp_config, write_mcp_config_file
from .spec import OrochiSpec, load_orochi_spec

__all__ = [
    "OrochiSpec",
    "load_orochi_spec",
    "build_orochi_mcp_config",
    "write_mcp_config_file",
    "resolve_orochi_token",
    "start_orochi_sidecar",
]
