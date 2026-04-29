"""Orochi -- Agent Communication Hub for the SciTeX ecosystem."""

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _v
    try:
        __version__ = _v("scitex-orochi")
    except PackageNotFoundError:
        __version__ = "0.0.0+local"
    del _v, PackageNotFoundError
except ImportError:  # pragma: no cover — only on ancient Pythons
    __version__ = "0.0.0+local"
from scitex_orochi._client import OrochiClient
from scitex_orochi._models import Message
from scitex_orochi._resources import collect_metrics
from scitex_orochi._server import OrochiServer

__all__ = [
    "OrochiClient",
    "OrochiServer",
    "Message",
    "collect_metrics",
]
