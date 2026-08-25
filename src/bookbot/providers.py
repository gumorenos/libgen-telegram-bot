from __future__ import annotations

import httpx

from .models import BookResult


class GutendexProvider:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(self, query: str, limit: int = 8) -> list[BookResult]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(f"{self.base_url}/books", params={"search": query})
            response.raise_for_status()
            payload = response.json()

        books: list[BookResult] = []
        for item in payload.get("results", [])[:limit]:
            authors = [a.get("name", "").strip() for a in item.get("authors", []) if a.get("name")]
            formats = {
                mime: url
                for mime, url in (item.get("formats") or {}).items()
                if isinstance(url, str) and url.startswith("https://")
            }
            books.append(
                BookResult(
                    source_id=str(item.get("id", "")),
                    title=(item.get("title") or "Sin título").strip(),
                    authors=authors,
                    languages=list(item.get("languages") or []),
                    download_count=item.get("download_count"),
                    formats=formats,
                )
            )
        return books


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
