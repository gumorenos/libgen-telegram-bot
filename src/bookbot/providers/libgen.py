from __future__ import annotations

import asyncio
from pathlib import Path
import re
import sqlite3

from ..models import BookResult
from .base import ProviderHealth

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class LibgenMetadataProvider:
    """Metadata-only adapter for a local LibGen-compatible SQLite FTS index.

    This provider performs no network requests, does not construct mirror/download
    URLs, and intentionally returns an empty ``formats`` mapping.
    """

    key = "libgen"
    label = "LibGen metadata"

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _uri(self) -> str:
        return f"file:{self.database_path.resolve()}?mode=ro"

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = _TOKEN.findall(query)[:12]
        if not tokens:
            return ""
        return " AND ".join(f'"{token}"' for token in tokens)

    def _search_sync(self, query: str, limit: int) -> list[BookResult]:
        fts_query = self._fts_query(query)
        if not fts_query or not self.database_path.is_file():
            return []

        connection = sqlite3.connect(self._uri(), uri=True, timeout=5)
        try:
            cursor = connection.execute(
                """
                SELECT rowid, title, author, language
                FROM libgen_book
                WHERE libgen_book MATCH ?
                LIMIT ?
                """,
                (fts_query, limit),
            )
            rows = cursor.fetchall()
        finally:
            connection.close()

        books: list[BookResult] = []
        for rowid, title, author, language in rows:
            books.append(
                BookResult(
                    source=self.key,
                    source_label=self.label,
                    source_id=f"row:{rowid}",
                    title=(title or "Sin título").strip(),
                    authors=[author.strip()] if isinstance(author, str) and author.strip() else [],
                    languages=[language.strip()] if isinstance(language, str) and language.strip() else [],
                    download_count=None,
                    formats={},
                )
            )
        return books

    async def search(self, query: str, limit: int = 8) -> list[BookResult]:
        return await asyncio.to_thread(self._search_sync, query, limit)

    def _health_sync(self) -> ProviderHealth:
        if not self.database_path.is_file():
            return ProviderHealth(self.key, self.label, False, "base de metadatos no encontrada")
        try:
            connection = sqlite3.connect(self._uri(), uri=True, timeout=5)
            try:
                connection.execute("SELECT rowid FROM libgen_book LIMIT 1").fetchone()
            finally:
                connection.close()
            return ProviderHealth(self.key, self.label, True, "índice SQLite local disponible")
        except sqlite3.Error as exc:
            return ProviderHealth(self.key, self.label, False, f"SQLite: {exc.__class__.__name__}")

    async def healthcheck(self) -> ProviderHealth:
        return await asyncio.to_thread(self._health_sync)
