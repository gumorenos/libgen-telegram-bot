# Provider architecture

The Telegram layer is intentionally independent from catalog integrations.
Every catalog implements the small `BookProvider` protocol in
`src/bookbot/providers/base.py` and returns normalized `BookResult` objects.

## Included providers

### `gutenberg`

`GutendexProvider` searches Project Gutenberg via Gutendex and may return HTTPS
file formats. The download pipeline separately validates every URL and redirect
against the Gutenberg hostname allowlist before a file is fetched.

### `libgen`

`LibgenMetadataProvider` is deliberately **metadata-only**. It reads a local,
read-only SQLite FTS index and returns title/author/language results with an empty
`formats` mapping. It performs no LibGen network requests and does not construct
mirror, MD5, torrent, or download URLs.

The provider expects a virtual table named `libgen_book` with at least these
columns:

```sql
CREATE VIRTUAL TABLE libgen_book USING fts5(
    title,
    author,
    language
);
```

FTS3/FTS4 indexes with the same columns also work because the provider uses the
standard SQLite `MATCH` query syntax.

If you already possess an authorized bibliographic CSV, a helper can build the
minimal metadata index without importing download-related fields:

```bash
python tools/build_metadata_index.py metadata.csv data/libgen-metadata.sqlite3
```

Then configure:

```dotenv
ENABLED_PROVIDERS=gutenberg,libgen
LIBGEN_METADATA_DB=/data/libgen-metadata.sqlite3
```

Use `/providers` and `/status` after restarting.

## Search routing

`/search query` searches every enabled provider concurrently and interleaves
results so one provider cannot monopolize the result list.

A provider can be selected explicitly with a prefix:

```text
/search gutenberg:don quixote
/search libgen:distributed systems
```

## Adding another lawful provider

1. Add a module under `src/bookbot/providers/`.
2. Implement `key`, `label`, `search()`, and `healthcheck()`.
3. Normalize output to `BookResult`.
4. Register it in `build_registry()`.
5. Add the provider key to `config._provider_keys()`.
6. Add tests that prove provider failures are isolated.

Only put URLs in `BookResult.formats` when the bot is intended and authorized to
download those files. Adding a provider does **not** automatically grant its
hosts permission in `security.is_allowed_download_url()`; that is a separate
security boundary by design.
