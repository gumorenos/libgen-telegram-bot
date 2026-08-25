from __future__ import annotations

import asyncio
import time

import httpx

from ..models import BookResult
from .base import ProviderHealth


class GutendexProvider:
    key = "gutenberg"
    label = "Project Gutenberg"

    def __init__(
        self,
        base_url: str,
        languages: tuple[str, ...] = (),
        timeout: float = 30.0,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.languages = tuple(languages)
        self.timeout = timeout
        self.retries = max(0, retries)
        self.transport = transport

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            self.timeout,
            connect=10.0,
            read=self.timeout,
            write=10.0,
            pool=10.0,
        )

    async def _get_books(self, query: str) -> dict:
        last_error: Exception | None = None
        params: dict[str, str] = {"search": query}
        if self.languages:
            params["languages"] = ",".join(self.languages)

        async with httpx.AsyncClient(
            timeout=self._timeout(),
            follow_redirects=True,
            transport=self.transport,
            headers={"User-Agent": "ebook-telegram-bot/0.5"},
        ) as client:
            for attempt in range(self.retries + 1):
                try:
                    response = await client.get(
                        f"{self.base_url}/books/",
                        params=params,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("Gutendex returned a non-object JSON payload")
                    return payload
                except (
                    httpx.TimeoutException,
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                ) as exc:
                    last_error = exc
                    if attempt >= self.retries:
                        raise
                    await asyncio.sleep(0.5 * (2**attempt))

        if last_error:
            raise last_error
        raise RuntimeError("Gutendex request failed")

    async def search(self, query: str, limit: int = 8) -> list[BookResult]:
        payload = await self._get_books(query)

        books: list[BookResult] = []
        for item in payload.get("results", [])[:limit]:
            authors = [
                a.get("name", "").strip()
                for a in item.get("authors", [])
                if a.get("name")
            ]
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
            payload = await self._get_books("don quixote")
            latency_ms = round((time.monotonic() - started) * 1000)
            results = len(payload.get("results", []))
            language_detail = (
                f"; idiomas={','.join(self.languages)}" if self.languages else ""
            )
            return ProviderHealth(
                self.key,
                self.label,
                True,
                f"{latency_ms} ms; {results} resultados de prueba{language_detail}",
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return ProviderHealth(self.key, self.label, False, type(exc).__name__)
