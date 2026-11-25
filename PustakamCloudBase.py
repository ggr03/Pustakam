"""
Pustakam (पुस्तकम्) — shared cloud-sync helpers (errors and safe file names).
"""
import re

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class CloudError(Exception):
    pass


class NotConnected(CloudError):
    pass


def sanitize_name(name, fallback="Untitled"):
    """Make a title safe as a file/folder name on OneDrive, Windows and Linux."""
    name = _BAD_CHARS.sub("-", name or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)[:120].strip()
    return name or fallback
