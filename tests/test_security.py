from bookbot.security import is_allowed_download_url, is_allowed_user, sanitize_filename


def test_allowlist():
    assert is_allowed_user(123, frozenset({123}))
    assert not is_allowed_user(456, frozenset({123}))
    assert not is_allowed_user(None, frozenset({123}))


def test_filename_sanitization():
    assert sanitize_filename("../../evil.epub") == "evil.epub"
    assert sanitize_filename("my:book?.epub") == "my_book_.epub"


def test_download_url_allowlist():
    assert is_allowed_download_url("https://www.gutenberg.org/ebooks/123.epub3.images")
    assert is_allowed_download_url("https://gutenberg.org/cache/epub/123/pg123.epub")
    assert not is_allowed_download_url("http://gutenberg.org/file.epub")
    assert not is_allowed_download_url("https://gutenberg.org.evil.example/file.epub")
    assert not is_allowed_download_url("https://example.com/file.epub")
