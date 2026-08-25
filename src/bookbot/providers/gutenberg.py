from __future__ import annotations

import time

import httpx

from ..models import BookResult
from .base import ProviderHealth


class GutendexProvider:
    key = "gutenberg"
    label = "Project Gutenberg"

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
                    source=self.key,
                    source_label=self.label,
                    source_id=str(item.get("id", "")),
                    title=(item.get("title") or "Sin título").strip(),
                    authors=authors,
                    languages=list(item.get("languages") or []),
                    download_count=item.get("download_count"),
                    formats=formats,
                )
            )
        return books

    async def healthcheck(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
                response = await client.get(f"{self.base_url}/books", params={"search": "don quixote"})
                response.raise_for_status()
                payload = response.json()
            latency_ms = round((time.monotonic() - started) * 1000)
            results = len(payload.get("results", []))
            return ProviderHealth(self.key, self.label, True, f"{latency_ms} ms; {results} resultados de prueba")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return ProviderHealth(self.key, self.label, False, type(exc).__name__)
