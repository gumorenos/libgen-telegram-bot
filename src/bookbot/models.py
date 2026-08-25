from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BookResult:
    source: str
    source_label: str
    source_id: str
    title: str
    authors: list[str]
    languages: list[str]
    download_count: int | None = None
    formats: dict[str, str] = field(default_factory=dict)

    @property
    def author_text(self) -> str:
        return ", ".join(self.authors) if self.authors else "Autor desconocido"
