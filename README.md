# Ebook Telegram Bot — modern VPS edition

Clean-room rewrite of the interaction pattern of an old Telegram ebook bot, designed for a private VPS deployment.

## What it does

- Searches **Project Gutenberg** via Gutendex.
- Shows per-user inline results in Telegram.
- Downloads allowed public-domain ebook files and sends them through Telegram.
- Lets allowlisted users upload and keep their own documents in a private local library.
- Uses per-user state instead of module-level globals.
- Runs with Docker Compose and long polling: **no public web port required**.
- Includes rate limiting, size limits, hostname allowlisting (including redirects), non-root container execution, dropped Linux capabilities, restart policy, logs, a heartbeat healthcheck, and `/status` end-to-end checks.

## What it intentionally does not do

This package does not automate downloads of copyrighted books from unauthorized sources. The provider layer can be extended with lawful catalogs or your own private library.

## Requirements

- Ubuntu/Debian VPS with Docker Engine + Docker Compose plugin.
- Telegram bot token from `@BotFather`.
- Your numeric Telegram user ID.

## Deployment

### 1. Clone the fork on your VPS

```bash
sudo mkdir -p /opt/ebook-telegram-bot
sudo chown "$USER":"$USER" /opt/ebook-telegram-bot
git clone https://github.com/gumorenos/libgen-telegram-bot.git /opt/ebook-telegram-bot
cd /opt/ebook-telegram-bot
mkdir -p data
sudo chown -R 10001:10001 data
```

### 2. Configure secrets

```bash
cp .env.example .env
nano .env
```

At minimum:

```dotenv
TELEGRAM_BOT_TOKEN=<your BotFather token>
ALLOWED_USER_IDS=
```

For the first boot only, leave `ALLOWED_USER_IDS` empty. The bot will refuse normal usage but `/whoami` remains available.

### 3. First boot and discover your user ID

```bash
docker compose up -d --build
docker compose logs -f --tail=100
```

Open the bot in Telegram and send:

```text
/whoami
```

Copy the numeric ID.

### 4. Lock the bot to your account

Edit `.env`:

```dotenv
ALLOWED_USER_IDS=123456789
```

Multiple users are comma separated:

```dotenv
ALLOWED_USER_IDS=123456789,987654321
```

Restart:

```bash
docker compose up -d
```

### 5. Verify

```bash
docker compose ps
docker compose logs --tail=100
```

In Telegram:

```text
/search don quixote
```

or simply send:

```text
don quixote
```

Select a result and then an available EPUB/PDF/TXT/HTML download.

You can also verify the live dependencies from Telegram:

```text
/status
```

This checks the bot process, every enabled provider, Project Gutenberg file access, and local library storage.

## Updating

If this lives in Git:

```bash
cd /opt/ebook-telegram-bot
git pull --ff-only
docker compose up -d --build
docker image prune -f
```

## Backup

The persistent data is only under `./data` and `.env`:

```bash
tar -czf ebook-bot-backup-$(date +%F).tgz .env data/
```

Do not commit `.env`.

## Useful operations

```bash
# Status
docker compose ps

# Live logs
docker compose logs -f --tail=200

# Restart
docker compose restart

# Stop
docker compose down

# Rebuild
docker compose up -d --build
```

## Security notes

- The container runs as an unprivileged user.
- No host ports are published.
- All Linux capabilities are dropped.
- `no-new-privileges` is enabled.
- Search/download state is stored in Telegram `user_data`, not globals shared between users.
- Remote downloads are limited to HTTPS hosts ending in `gutenberg.org`; every redirect is revalidated before following it.
- The default maximum outbound file is 48 MB, below Telegram's hosted Bot API `sendDocument` limit.
- User uploads default to 19 MB, below the hosted Bot API `getFile` download limit.
- Uploaded filenames are sanitized before being written to disk.

## Tests

With a Python environment:

```bash
python -m pip install -e '.[dev]'
pytest -q
```

At minimum, before deployment:

```bash
python -m compileall -q src tests
```

GitHub Actions runs compile checks and `pytest` automatically on pushes and pull requests.

## Next sensible improvements

1. SQLite index for the personal uploaded-file library.
2. `/get` command to retrieve an uploaded file.
3. Covers and richer result cards.
4. Pagination.
5. Open Library metadata provider.
6. Automatic duplicate detection by SHA-256.
7. Optional self-hosted Telegram Bot API server if you genuinely need files larger than hosted Bot API limits.

## Multi-provider architecture

The bot now uses a provider registry instead of wiring Telegram directly to Gutendex.

Enabled providers are configured with:

```dotenv
ENABLED_PROVIDERS=gutenberg
```

Use `/providers` to list the active catalogs. `/search query` searches all enabled providers and interleaves their results. To target one provider, prefix the query:

```text
/search gutenberg:don quixote
```

### Optional LibGen metadata adapter

A **metadata-only**, local SQLite adapter is included but disabled by default. It makes no LibGen network requests, returns no download URLs, and does not construct mirror/MD5/torrent links. It expects a compatible SQLite FTS table named `libgen_book` with `title`, `author`, and `language` columns.

If you already possess a bibliographic CSV that you are authorized to use, you can build the minimal index locally:

```bash
python tools/build_metadata_index.py metadata.csv data/libgen-metadata.sqlite3
```

The helper deliberately imports only title, author and language metadata. Then configure:

```dotenv
ENABLED_PROVIDERS=gutenberg,libgen
LIBGEN_METADATA_DB=/data/libgen-metadata.sqlite3
```

Then rebuild/restart and check `/providers` and `/status`. The download pipeline remains restricted to the Gutenberg HTTPS allowlist. See `docs/PROVIDERS.md` for the provider contract and extension guide.
