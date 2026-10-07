"""Small filesystem and naming helpers shared by the app and the library."""

import os
import re


def safe_join(base_dir: str, filename: str) -> str | None:
    """Join filename onto base_dir, returning None if the result escapes base_dir."""
    safe_dir  = os.path.realpath(base_dir)
    candidate = os.path.realpath(os.path.join(safe_dir, filename))
    return candidate if candidate.startswith(safe_dir + os.sep) else None


def sanitize_download_name(name: str) -> str:
    """Remove characters invalid in filenames while preserving non-ASCII."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', name).strip()
    return cleaned or 'converted'


def filename_stem(filename: str) -> str:
    """Return the filename without its last extension."""
    return filename.rsplit('.', 1)[0] if '.' in filename else filename


def remove_quietly(path: str | None) -> None:
    """Delete a file if it exists, ignoring errors (used for temp-file cleanup)."""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
