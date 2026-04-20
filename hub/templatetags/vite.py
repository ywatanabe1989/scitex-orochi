"""Vite bundle lookup for Django templates.

Reads hub/static/hub/dist/.vite/manifest.json (written by `vite build`)
and resolves a source entry (e.g. "src/index.ts") to its hashed bundle
filename (e.g. "orochi-DeCs6OVi.js").

Used by dashboard.html to load the single orochi-hub frontend bundle
without having to hard-code the content hash after every build.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


def _manifest_path() -> Path:
    # hub/static/hub/dist/.vite/manifest.json
    return (
        Path(__file__).resolve().parent.parent
        / "static"
        / "hub"
        / "dist"
        / ".vite"
        / "manifest.json"
    )


@lru_cache(maxsize=1)
def _load_manifest_cached(mtime: float) -> dict:
    """Load the Vite manifest; cache keyed on mtime so reloads pick up rebuilds.

    ``mtime`` is the cache key (lru_cache busts when it changes on disk).
    The body treats it as a sentinel — no-op reference so linters see a use.
    """
    _ = mtime
    path = _manifest_path()
    with path.open("r") as f:
        return json.load(f)


def _load_manifest() -> dict:
    path = _manifest_path()
    if not path.exists():
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    # In DEBUG we bypass the cache so rebuilds are picked up without restart.
    if getattr(settings, "DEBUG", False):
        with path.open("r") as f:
            return json.load(f)
    return _load_manifest_cached(mtime)


@register.simple_tag
def vite_bundle(entry: str = "src/index.ts") -> str:
    """Return the {% static %}-ified URL for the hashed bundle of `entry`.

    If the manifest is missing (e.g. fresh checkout without `npm run build`),
    returns an empty string so the template gracefully omits the <script> tag.
    """
    manifest = _load_manifest()
    record = manifest.get(entry)
    if not record:
        return ""
    file_rel = record.get("file")
    if not file_rel:
        return ""
    return static(f"hub/dist/{file_rel}")
