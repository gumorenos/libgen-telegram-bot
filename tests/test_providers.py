from bookbot.models import BookResult
from bookbot.providers import preferred_downloads


def test_preferred_downloads_order_and_dedup():
    book = BookResult(
        source_id="1",
        title="Test",
        authors=["A"],
        languages=["en"],
        download_count=1,
        formats={
            "text/plain": "https://www.gutenberg.org/a.txt",
            "application/epub+zip": "https://www.gutenberg.org/a.epub",
            "application/pdf": "https://www.gutenberg.org/a.pdf",
        },
    )
    downloads = preferred_downloads(book)
    assert [x[0] for x in downloads] == ["EPUB", "PDF", "TXT"]
