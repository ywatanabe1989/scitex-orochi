"""Django template tag to resolve Vite-hashed bundle URLs from manifest.json.

Reads `hub/static/hub/dist/.vite/manifest.json` (written by `vite build`)
and maps an entry key such as `src/index.ts` to the hashed output
filename. When the bundle hasn't been built yet (e.g. in CI before the
first build, or on a fresh dev orochi_machine), returns an empty string so the
caller template can `{% if %}`-guard emission of the `<script>` tag.
"""

import json
from pathlib import Path

from django import template
from django.conf import settings

register = template.Library()

_MANIFEST_CACHE: dict = {}


def _load_manifest(manifest_path: Path) -> dict:
    try:
        mtime = manifest_path.stat().st_mtime
    except FileNotFoundError:
        return {}
    key = (str(manifest_path), mtime)
    cached = _MANIFEST_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    _MANIFEST_CACHE.clear()
    _MANIFEST_CACHE[key] = data
    return data


@register.simple_tag
def vite_bundle(entry: str) -> str:
    """Return the /static/... URL for a Vite bundle entry, or '' if missing."""
    static_root = Path(settings.BASE_DIR) / "hub" / "static" / "hub" / "dist"
    manifest = _load_manifest(static_root / ".vite" / "manifest.json")
    record = manifest.get(entry)
    if not record or "file" not in record:
        return ""
    return f"/static/hub/dist/{record['file']}"
