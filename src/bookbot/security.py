from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlparse

_ALLOWED_GUTENBERG_SUFFIXES = ("gutenberg.org",)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def is_allowed_user(user_id: int | None, allowed_ids: frozenset[int]) -> bool:
    return user_id is not None and user_id in allowed_ids


def sanitize_filename(name: str) -> str:
    base = Path(name).name.strip().replace("\x00", "")
    cleaned = _SAFE_NAME.sub("_", base).strip(" .")
    return cleaned[:180] or "document.bin"


def is_allowed_download_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    return any(host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_GUTENBERG_SUFFIXES)
