"""Media file storage for Orochi."""

from __future__ import annotations

import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scitex_orochi._config import MEDIA_MAX_SIZE, MEDIA_ROOT


class MediaStore:
    """Stores uploaded files on disk under MEDIA_ROOT/<YYYY-MM>/<uuid>.<ext>."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or MEDIA_ROOT)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, filename: str, mime_type: str = "") -> dict:
        """Save file bytes to disk. Returns attachment metadata dict."""
        if len(data) > MEDIA_MAX_SIZE:
            raise ValueError(f"File too large: {len(data)} > {MEDIA_MAX_SIZE}")

        if not mime_type:
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        ext = Path(filename).suffix or mimetypes.guess_extension(mime_type) or ""
        file_id = str(uuid.uuid4())
        subdir = datetime.now(timezone.utc).strftime("%Y-%m")
        dest_dir = self.root / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"{file_id}{ext}"
        dest_file.write_bytes(data)

        url = f"/media/{subdir}/{file_id}{ext}"
        return {
            "file_id": file_id,
            "url": url,
            "mime_type": mime_type,
            "filename": filename,
            "size": len(data),
        }
