from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import BookResult


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    key: str
    label: str
    ok: bool
    detail: str = ""


class BookProvider(Protocol):
    key: str
    label: str

    async def search(self, query: str, limit: int = 8) -> list[BookResult]: ...

    async def healthcheck(self) -> ProviderHealth: ...
