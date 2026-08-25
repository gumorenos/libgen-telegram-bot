from __future__ import annotations

from pathlib import Path

from ..models import BookResult
from .base import BookProvider, ProviderHealth
from .gutenberg import GutendexProvider
from .libgen import LibgenMetadataProvider
from .registry import ProviderRegistry


def preferred_downloads(book: BookResult) -> list[tuple[str, str]]:
    preferred = [
        ("application/epub+zip", "EPUB"),
        ("application/pdf", "PDF"),
        ("text/plain; charset=utf-8", "TXT"),
        ("text/plain", "TXT"),
        ("text/html; charset=utf-8", "HTML"),
        ("text/html", "HTML"),
    ]
    out: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for mime, label in preferred:
        url = book.formats.get(mime)
        if url and url not in seen_urls:
            out.append((label, url))
            seen_urls.add(url)
    return out


def build_registry(
    *,
    enabled: tuple[str, ...],
    gutendex_base_url: str,
    libgen_metadata_db: Path,
) -> ProviderRegistry:
    providers: list[BookProvider] = []
    for key in enabled:
        if key == "gutenberg":
            providers.append(GutendexProvider(gutendex_base_url))
        elif key == "libgen":
            providers.append(LibgenMetadataProvider(libgen_metadata_db))
    return ProviderRegistry(providers)


__all__ = [
    "BookProvider",
    "ProviderHealth",
    "GutendexProvider",
    "LibgenMetadataProvider",
    "ProviderRegistry",
    "build_registry",
    "preferred_downloads",
]
