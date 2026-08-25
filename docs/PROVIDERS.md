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

`LibgenProvider` is a **hybrid metadata-only** provider. It can use two sources:

1. `LibgenMetadataProvider`: an optional local, read-only SQLite FTS index.
2. `LibgenLiveProvider`: optional live search against operator-configured HTTPS mirrors.

The local index is tried first. If it is missing, fails, or does not fill the
requested result limit, the live provider is used. Duplicate title/author pairs
are removed. Both sources return an empty `formats` mapping: this integration
searches metadata but does not expose LibGen download, mirror, MD5 or torrent URLs.

Configure the provider with:

```dotenv
ENABLED_PROVIDERS=gutenberg,libgen
LIBGEN_METADATA_DB=/data/libgen-metadata.sqlite3
LIBGEN_LIVE_MIRRORS=https://mirror-one.example,https://mirror-two.example
```

`LIBGEN_METADATA_DB` is optional in practice. If the file does not exist and at
least one live mirror is configured, `/search libgen:query` searches live.
`LIBGEN_LIVE_MIRRORS` may also be empty when you want local-index-only mode.
Mirrors must be credential-free HTTPS base URLs and are supplied by the operator;
the project intentionally ships with no hard-coded mirror list.

The live provider tries the last successful mirror first and fails over to the
remaining configured mirrors on HTTP errors or an unrecognized search page.
`/status` reports whether the local and live sides are healthy.

### Optional local metadata index

The local provider expects a virtual table named `libgen_book` with at least:

```sql
CREATE VIRTUAL TABLE libgen_book USING fts5(
    title,
    author,
    language
);
```

FTS3/FTS4 indexes with the same columns also work because the provider uses the
standard SQLite `MATCH` syntax.

If you already possess a bibliographic CSV you are authorized to use:

```bash
python tools/build_metadata_index.py metadata.csv data/libgen-metadata.sqlite3
```

The helper imports only title, author and language metadata.

## Search routing

`/search query` searches every enabled top-level provider concurrently and
interleaves results so one provider cannot monopolize the result list.

A provider can be selected explicitly with a prefix:

```text
/search gutenberg:don quixote
/search libgen:distributed systems
```

For `libgen`, that one command transparently uses local metadata first and live
search as fallback. You do not have to change the Telegram command when an index
is later added or removed.

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
