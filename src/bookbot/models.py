from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BookResult:
    source_id: str
    title: str
    authors: list[str]
    languages: list[str]
    download_count: int | None
    formats: dict[str, str]

    @property
    def author_text(self) -> str:
        return ", ".join(self.authors) if self.authors else "Autor desconocido"
