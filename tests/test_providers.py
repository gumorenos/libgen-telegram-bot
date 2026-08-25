import asyncio
import sqlite3

from bookbot.models import BookResult
from bookbot.providers import LibgenMetadataProvider, ProviderRegistry, preferred_downloads
from bookbot.providers.base import ProviderHealth


def _book(source: str, title: str) -> BookResult:
    return BookResult(
        source=source,
        source_label=source.title(),
        source_id=title,
        title=title,
        authors=["A"],
        languages=["en"],
        download_count=1,
        formats={},
    )


def test_preferred_downloads_order_and_dedup():
    book = _book("gutenberg", "Test")
    book.formats = {
        "text/plain": "https://www.gutenberg.org/a.txt",
        "application/epub+zip": "https://www.gutenberg.org/a.epub",
        "application/pdf": "https://www.gutenberg.org/a.pdf",
    }
    downloads = preferred_downloads(book)
    assert [x[0] for x in downloads] == ["EPUB", "PDF", "TXT"]


class FakeProvider:
    def __init__(self, key: str, titles: list[str]):
        self.key = key
        self.label = key.title()
        self.titles = titles

    async def search(self, query: str, limit: int = 8):
        return [_book(self.key, title) for title in self.titles[:limit]]

    async def healthcheck(self):
        return ProviderHealth(self.key, self.label, True, "ok")


def test_registry_round_robin_and_scope():
    registry = ProviderRegistry([FakeProvider("a", ["a1", "a2"]), FakeProvider("b", ["b1", "b2"])])
    books, errors = asyncio.run(registry.search("x", 4))
    assert not errors
    assert [book.title for book in books] == ["a1", "b1", "a2", "b2"]

    books, errors = asyncio.run(registry.search("x", 2, "b"))
    assert not errors
    assert [book.title for book in books] == ["b1", "b2"]


def test_libgen_metadata_provider_is_local_and_has_no_downloads(tmp_path):
    db = tmp_path / "metadata.sqlite3"
    connection = sqlite3.connect(db)
    connection.execute("CREATE VIRTUAL TABLE libgen_book USING fts3(title, author, language)")
    connection.execute(
        "INSERT INTO libgen_book(title, author, language) VALUES (?, ?, ?)",
        ("Distributed Systems", "Example Author", "English"),
    )
    connection.commit()
    connection.close()

    provider = LibgenMetadataProvider(db)
    books = asyncio.run(provider.search("Distributed Systems", 5))
    assert len(books) == 1
    assert books[0].source == "libgen"
    assert books[0].formats == {}
    assert "md5" not in books[0].source_id.lower()


def test_metadata_index_builder_ignores_download_fields(tmp_path):
    import csv
    import importlib.util

    module_path = __import__("pathlib").Path(__file__).parents[1] / "tools" / "build_metadata_index.py"
    spec = importlib.util.spec_from_file_location("build_metadata_index", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    source = tmp_path / "metadata.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Title", "Author", "Language", "MD5", "Mirror"])
        writer.writeheader()
        writer.writerow({
            "Title": "Example Book",
            "Author": "Example Author",
            "Language": "English",
            "MD5": "do-not-import",
            "Mirror": "https://example.invalid/file",
        })

    target = tmp_path / "index.sqlite3"
    assert module.build_index(source, target) == 1
    connection = sqlite3.connect(target)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(libgen_book)")]
        row = connection.execute("SELECT title, author, language FROM libgen_book").fetchone()
    finally:
        connection.close()
    assert columns == ["title", "author", "language"]
    assert row == ("Example Book", "Example Author", "English")
