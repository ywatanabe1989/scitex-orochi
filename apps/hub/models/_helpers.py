"""Module-level helpers shared by the model package.

Split out of the original 699-line ``hub/models.py`` so each domain
sub-module (``_identity``, ``_messaging``, etc.) can import the
helpers without circular dependencies. ``normalize_channel_name`` is
also part of the public ``hub.models`` surface (imported by
``hub/apps.py``).
"""

import secrets


def _generate_workspace_token():
    return f"wks_{secrets.token_hex(16)}"


def normalize_channel_name(name: str) -> str:
    """Canonicalize a group-channel name to ``#<name>``.

    Group channels live under the ``#`` namespace so the sidebar can
    render them as Slack-style references. Direct-message channels use
    the reserved ``dm:`` prefix and are passed through unchanged. Empty
    or whitespace-only names raise ``ValueError`` so that callers fail
    loudly at the boundary instead of silently creating ``#`` rows.

    Why this exists: prior to todo#326 the hub had two separate Channel
    rows for ``general`` and ``#general`` because clients posted with
    inconsistent prefixes and ``Channel.objects.get_or_create`` is
    name-sensitive. The read-side fix in 2f4e073 normalized the sidebar
    response, but the database still accumulated bare-name rows on every
    write. This helper closes the write path.
    """
    if name is None:
        raise ValueError("channel name cannot be None")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("channel name cannot be empty")
    if cleaned.startswith("dm:"):
        return cleaned
    if cleaned.startswith("#"):
        return cleaned
    return f"#{cleaned}"
