from __future__ import annotations

from ..models import BookResult
from .base import BookProvider, ProviderHealth


class LibgenProvider:
    """Prefer a local metadata index and fall back to live LibGen search."""

    key = "libgen"
    label = "LibGen"

    def __init__(
        self,
        local_provider: BookProvider | None = None,
        live_provider: BookProvider | None = None,
    ) -> None:
        self.local_provider = local_provider
        self.live_provider = live_provider

    @staticmethod
    def _dedupe(books: list[BookResult]) -> list[BookResult]:
        seen: set[tuple[str, tuple[str, ...]]] = set()
        out: list[BookResult] = []
        for book in books:
            key = (
                book.title.casefold().strip(),
                tuple(author.casefold().strip() for author in book.authors),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(book)
        return out

    async def search(self, query: str, limit: int = 8) -> list[BookResult]:
        results: list[BookResult] = []
        failures: list[Exception] = []

        if self.local_provider is not None:
            try:
                results.extend(await self.local_provider.search(query, limit))
            except Exception as exc:
                failures.append(exc)

        if len(results) < limit and self.live_provider is not None:
            try:
                results.extend(await self.live_provider.search(query, limit))
            except Exception as exc:
                failures.append(exc)

        results = self._dedupe(results)
        if results:
            return results[:limit]
        if failures:
            raise RuntimeError("LibGen sources unavailable") from failures[-1]
        return []

    async def healthcheck(self) -> ProviderHealth:
        parts: list[str] = []
        ok = False

        if self.local_provider is not None:
            local = await self.local_provider.healthcheck()
            ok = ok or local.ok
            parts.append(f"local={'ok' if local.ok else 'off'}")

        if self.live_provider is not None:
            live = await self.live_provider.healthcheck()
            ok = ok or live.ok
            parts.append(f"live={'ok' if live.ok else 'off'}")

        if self.local_provider is None and self.live_provider is None:
            parts.append("sin fuentes configuradas")

        return ProviderHealth(
            self.key,
            self.label,
            ok,
            ", ".join(parts),
        )
