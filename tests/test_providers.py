import asyncio
import sqlite3

import httpx

from bookbot.models import BookResult
from bookbot.providers import (
    LibgenLiveProvider,
    LibgenMetadataProvider,
    LibgenProvider,
    ProviderRegistry,
    preferred_downloads,
)
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
    def __init__(self, key: str, titles: list[str], fail: bool = False):
        self.key = key
        self.label = key.title()
        self.titles = titles
        self.fail = fail

    async def search(self, query: str, limit: int = 8):
        if self.fail:
            raise RuntimeError("provider failed")
        return [_book(self.key, title) for title in self.titles[:limit]]

    async def healthcheck(self):
        return ProviderHealth(self.key, self.label, not self.fail, "ok" if not self.fail else "failed")


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
    assert books[0].source_label == "LibGen local metadata"
    assert books[0].formats == {}
    assert "md5" not in books[0].source_id.lower()


def test_libgen_live_parser_returns_metadata_without_downloads():
    html = """
    <html><body>
      <table class="c">
        <tr><td>ID</td><td>Author</td><td>Title</td><td>Publisher</td><td>Year</td><td>Pages</td><td>Language</td><td>Size</td><td>Ext</td></tr>
        <tr>
          <td>42</td><td><a>Jane Doe</a></td>
          <td><a href="book/index.php?md5=not-imported">Systems Book</a></td>
          <td>Example</td><td>2020</td><td>100</td><td>English</td><td>1 MB</td><td>pdf</td>
        </tr>
      </table>
    </body></html>
    """
    books = LibgenLiveProvider._parse_search_page(html, 5)
    assert len(books) == 1
    assert books[0].title == "Systems Book"
    assert books[0].authors == ["Jane Doe"]
    assert books[0].source_label == "LibGen live"
    assert books[0].formats == {}


def test_libgen_live_failover_uses_second_mirror():
    html = """
    <table class="c">
      <tr><td>ID</td><td>Author</td><td>Title</td><td>Publisher</td><td>Year</td><td>Pages</td><td>Language</td><td>Size</td><td>Ext</td></tr>
      <tr><td>7</td><td>A</td><td><a href="book/7">Fallback Book</a></td><td>P</td><td>2024</td><td>10</td><td>English</td><td>1 MB</td><td>epub</td></tr>
    </table>
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "bad.example":
            return httpx.Response(503, request=request)
        return httpx.Response(200, text=html, request=request)

    provider = LibgenLiveProvider(
        ("https://bad.example", "https://good.example"),
        transport=httpx.MockTransport(handler),
    )
    books = asyncio.run(provider.search("fallback", 5))
    assert [book.title for book in books] == ["Fallback Book"]
    assert provider._active_mirror == "https://good.example"


def test_libgen_live_rejects_non_https_mirror():
    try:
        LibgenLiveProvider(("http://unsafe.example",))
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("expected mirror validation failure")


def test_hybrid_libgen_falls_back_to_live_and_deduplicates():
    local = FakeProvider("local", ["Same Book"])
    live = FakeProvider("live", ["Same Book", "Other Book"])
    provider = LibgenProvider(local_provider=local, live_provider=live)
    books = asyncio.run(provider.search("book", 3))
    assert [book.title for book in books] == ["Same Book", "Other Book"]

    failing_local = FakeProvider("local", [], fail=True)
    live_only = FakeProvider("live", ["Live Book"])
    provider = LibgenProvider(local_provider=failing_local, live_provider=live_only)
    books = asyncio.run(provider.search("book", 3))
    assert [book.title for book in books] == ["Live Book"]


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
