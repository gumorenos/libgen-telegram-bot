from __future__ import annotations

import asyncio
from collections.abc import Iterable
import unicodedata

from ..models import BookResult
from .base import BookProvider, ProviderHealth


_LANGUAGE_ALIASES: dict[str, set[str]] = {
    "en": {"en", "english"},
    "es": {"es", "spanish", "espanol", "castilian", "castellano"},
    "fr": {"fr", "french", "francais"},
    "de": {"de", "german", "deutsch"},
    "it": {"it", "italian", "italiano"},
    "pt": {"pt", "portuguese", "portugues"},
    "ru": {"ru", "russian"},
    "zh": {"zh", "chinese"},
    "ja": {"ja", "japanese"},
    "nl": {"nl", "dutch"},
    "pl": {"pl", "polish"},
    "uk": {"uk", "ukrainian"},
    "ar": {"ar", "arabic"},
}


def _normalize_language(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _matches_languages(book: BookResult, allowed: tuple[str, ...]) -> bool:
    if not allowed:
        return True
    reported = {_normalize_language(value) for value in book.languages if value.strip()}
    if not reported:
        return False
    accepted: set[str] = set()
    for code in allowed:
        accepted.update(_LANGUAGE_ALIASES.get(code, {code}))
    return bool(reported & accepted)


class ProviderRegistry:
    def __init__(
        self,
        providers: Iterable[BookProvider],
        languages: tuple[str, ...] = (),
    ) -> None:
        self._providers = {provider.key: provider for provider in providers}
        self.languages = tuple(languages)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._providers)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(provider.label for provider in self._providers.values())

    def has(self, key: str) -> bool:
        return key in self._providers

    def _filter_languages(self, books: list[BookResult]) -> list[BookResult]:
        if not self.languages:
            return books
        return [book for book in books if _matches_languages(book, self.languages)]

    async def search(
        self,
        query: str,
        limit: int,
        provider_key: str | None = None,
    ) -> tuple[list[BookResult], list[str]]:
        if provider_key:
            provider = self._providers.get(provider_key)
            if provider is None:
                return [], [f"Proveedor desconocido: {provider_key}"]
            try:
                books = await provider.search(query, limit)
                return self._filter_languages(books)[:limit], []
            except Exception as exc:
                return [], [f"{provider.label}: {exc.__class__.__name__}"]

        providers = list(self._providers.values())
        if not providers:
            return [], ["No hay proveedores habilitados"]

        outcomes = await asyncio.gather(
            *(provider.search(query, limit) for provider in providers),
            return_exceptions=True,
        )
        buckets: list[list[BookResult]] = []
        errors: list[str] = []
        for provider, outcome in zip(providers, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                errors.append(f"{provider.label}: {outcome.__class__.__name__}")
                buckets.append([])
            else:
                buckets.append(self._filter_languages(outcome))

        merged: list[BookResult] = []
        offset = 0
        while len(merged) < limit:
            added = False
            for bucket in buckets:
                if offset < len(bucket):
                    merged.append(bucket[offset])
                    added = True
                    if len(merged) >= limit:
                        break
            if not added:
                break
            offset += 1
        return merged, errors

    async def healthcheck(self) -> list[ProviderHealth]:
        providers = list(self._providers.values())
        outcomes = await asyncio.gather(
            *(provider.healthcheck() for provider in providers),
            return_exceptions=True,
        )
        health: list[ProviderHealth] = []
        for provider, outcome in zip(providers, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                health.append(
                    ProviderHealth(
                        provider.key,
                        provider.label,
                        False,
                        outcome.__class__.__name__,
                    )
                )
            else:
                health.append(outcome)
        return health
