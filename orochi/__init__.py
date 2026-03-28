"""Backward-compatibility shim -- use scitex_orochi instead."""

from scitex_orochi import OrochiClient, OrochiServer, Message, __version__

__all__ = ["OrochiClient", "OrochiServer", "Message", "__version__"]
