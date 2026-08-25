from __future__ import annotations

import asyncio
from collections.abc import Iterable

from ..models import BookResult
from .base import BookProvider, ProviderHealth


class ProviderRegistry:
    def __init__(self, providers: Iterable[BookProvider]) -> None:
        self._providers = {provider.key: provider for provider in providers}

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._providers)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(provider.label for provider in self._providers.values())

    def has(self, key: str) -> bool:
        return key in self._providers

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
                return (await provider.search(query, limit))[:limit], []
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
                buckets.append(outcome)

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
                health.append(ProviderHealth(provider.key, provider.label, False, outcome.__class__.__name__))
            else:
                health.append(outcome)
        return health
