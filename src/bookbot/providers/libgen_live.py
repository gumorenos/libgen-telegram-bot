from __future__ import annotations

from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ..models import BookResult
from .base import ProviderHealth


class LibgenLiveProvider:
    """Metadata-only live LibGen search with configurable mirror failover.

    This provider intentionally returns no download URLs. Mirrors must be supplied
    by the operator and must be credential-free HTTPS URLs.
    """

    key = "libgen-live"
    label = "LibGen live"

    def __init__(
        self,
        mirrors: tuple[str, ...],
        timeout: float = 12.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.mirrors = self._normalize_mirrors(mirrors)
        self.timeout = timeout
        self.transport = transport
        self._active_mirror: str | None = None

    @staticmethod
    def _normalize_mirrors(mirrors: tuple[str, ...]) -> tuple[str, ...]:
        out: list[str] = []
        for raw in mirrors:
            value = raw.strip().rstrip("/")
            if not value:
                continue
            parsed = urlparse(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("LibGen mirrors must be credential-free HTTPS URLs")
            if value not in out:
                out.append(value)
        return tuple(out)

    @staticmethod
    def _parse_search_page(html: str, limit: int) -> list[BookResult]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="c")
        if table is None:
            text = soup.get_text(" ", strip=True).lower()
            if "0 books" in text or "0 files" in text or "nothing found" in text:
                return []
            raise ValueError("Unrecognized LibGen search page")

        books: list[BookResult] = []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 9:
                continue

            source_id = cells[0].get_text(" ", strip=True)
            authors = [
                value.strip()
                for value in cells[1].stripped_strings
                if value.strip()
            ]
            title_cell = cells[2]
            title_link = title_cell.find("a", href=True)
            title = (
                title_link.get_text(" ", strip=True)
                if title_link
                else title_cell.get_text(" ", strip=True)
            )
            language = cells[6].get_text(" ", strip=True)

            if not title:
                continue

            books.append(
                BookResult(
                    source="libgen",
                    source_label="LibGen live",
                    source_id=source_id or f"row:{len(books) + 1}",
                    title=title,
                    authors=authors[:4],
                    languages=[language] if language else [],
                    download_count=None,
                    formats={},
                )
            )
            if len(books) >= limit:
                break
        return books

    def _ordered_mirrors(self) -> list[str]:
        ordered = list(self.mirrors)
        if self._active_mirror in ordered:
            ordered.remove(self._active_mirror)
            ordered.insert(0, self._active_mirror)
        return ordered

    async def _search_one(
        self,
        mirror: str,
        query: str,
        limit: int,
    ) -> list[BookResult]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            transport=self.transport,
            headers={"User-Agent": "ebook-telegram-bot/0.3"},
        ) as client:
            response = await client.get(
                f"{mirror}/search.php",
                params={
                    "req": query,
                    "open": "0",
                    "view": "simple",
                    "phrase": "1",
                    "column": "def",
                },
            )
            response.raise_for_status()
            books = self._parse_search_page(response.text, limit)
            self._active_mirror = mirror
            return books

    async def search(self, query: str, limit: int = 8) -> list[BookResult]:
        if not self.mirrors:
            raise RuntimeError("no LibGen live mirrors configured")

        failures: list[str] = []
        for mirror in self._ordered_mirrors():
            try:
                return await self._search_one(mirror, query, limit)
            except (httpx.HTTPError, ValueError) as exc:
                failures.append(f"{urlparse(mirror).hostname}: {exc.__class__.__name__}")

        raise RuntimeError("all LibGen live mirrors failed: " + ", ".join(failures))

    async def healthcheck(self) -> ProviderHealth:
        if not self.mirrors:
            return ProviderHealth(self.key, self.label, False, "sin mirrors configurados")

        async with httpx.AsyncClient(
            timeout=min(self.timeout, 8.0),
            follow_redirects=True,
            transport=self.transport,
            headers={"User-Agent": "ebook-telegram-bot-status/0.3"},
        ) as client:
            for mirror in self._ordered_mirrors():
                try:
                    response = await client.get(mirror)
                    response.raise_for_status()
                    self._active_mirror = mirror
                    return ProviderHealth(
                        self.key,
                        self.label,
                        True,
                        f"mirror activo: {urlparse(mirror).hostname}",
                    )
                except httpx.HTTPError:
                    continue

        return ProviderHealth(self.key, self.label, False, "ningún mirror respondió")
