from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import shutil
import tempfile
import time
from urllib.parse import urljoin

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings
from .healthcheck import HEARTBEAT
from .library import PersonalLibrary
from .models import BookResult
from .providers import ProviderRegistry, build_registry, preferred_downloads
from .security import is_allowed_download_url, is_allowed_user, sanitize_filename

logger = logging.getLogger(__name__)


async def _require_allowed(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    if user and is_allowed_user(user.id, settings.allowed_user_ids):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("No autorizado.")
    return False


async def post_init(application: Application) -> None:
    HEARTBEAT.touch()
    commands = [
        ("start", "Inicio"),
        ("search", "Buscar ebooks"),
        ("providers", "Ver catálogos habilitados"),
        ("library", "Ver biblioteca privada"),
        ("status", "Estado del servicio"),
        ("whoami", "Mostrar mi Telegram user ID"),
        ("help", "Ayuda"),
    ]
    await application.bot.set_my_commands(commands)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return
    language_note = (
        f"\nIdiomas filtrados: {', '.join(settings.search_languages)}"
        if settings.search_languages
        else "\nIdiomas: todos"
    )
    await update.effective_message.reply_text(
        "📚 Bot privado de ebooks\n\n"
        "Busca en los catálogos habilitados con /search <texto> o simplemente envía un título/autor.\n"
        "También puedes subir documentos propios (máx. configurado) para guardarlos en tu biblioteca.\n\n"
        "Comandos: /search, /providers, /library, /status, /whoami, /help"
        + language_note
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        await update.effective_message.reply_text(f"Tu Telegram user ID es: {user.id}")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return

    lines = ["🟢 Bot: OK"]
    if settings.search_languages:
        lines.append(f"🔎 Idiomas: {', '.join(settings.search_languages)}")
    else:
        lines.append("🔎 Idiomas: todos")

    registry: ProviderRegistry = context.application.bot_data["providers"]
    for health in await registry.healthcheck():
        icon = "🟢" if health.ok else "🔴"
        detail = f" — {health.detail}" if health.detail else ""
        lines.append(
            f"{icon} {health.label}: {'OK' if health.ok else 'ERROR'}{detail}"
        )

    if registry.has("gutenberg"):
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            try:
                response = await client.get(
                    "https://www.gutenberg.org/",
                    headers={"User-Agent": "ebook-telegram-bot-status/0.2"},
                )
                response.raise_for_status()
                lines.append("🟢 Project Gutenberg files: OK")
            except httpx.HTTPError as exc:
                logger.warning("Project Gutenberg status check failed: %s", exc)
                lines.append("🔴 Project Gutenberg files: ERROR")

    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(settings.data_dir)
        free_gb = usage.free / (1024 ** 3)
        lines.append(f"🟢 Biblioteca local: OK — {free_gb:.1f} GB libres")
    except OSError as exc:
        logger.warning("Local library status check failed: %s", exc)
        lines.append("🔴 Biblioteca local: ERROR")

    await update.effective_message.reply_text("\n".join(lines))


async def providers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return
    registry: ProviderRegistry = context.application.bot_data["providers"]
    if not registry.keys:
        await update.effective_message.reply_text("No hay proveedores habilitados.")
        return
    lines = ["📚 Proveedores habilitados:"]
    for key, label in zip(registry.keys, registry.labels, strict=True):
        lines.append(f"• {key}: {label}")
    lines.append("")
    if settings.search_languages:
        lines.append(f"Idiomas: {', '.join(settings.search_languages)}")
    else:
        lines.append("Idiomas: todos")
    lines.append(
        "Para limitar una búsqueda usa /search proveedor:consulta, por ejemplo /search gutenberg:don quixote"
    )
    await update.effective_message.reply_text("\n".join(lines))


def _split_provider_query(
    raw: str,
    registry: ProviderRegistry,
) -> tuple[str | None, str]:
    prefix, sep, remainder = raw.partition(":")
    key = prefix.strip().lower()
    if sep and registry.has(key) and remainder.strip():
        return key, remainder.strip()
    return None, raw.strip()


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip()
    if not query:
        await update.effective_message.reply_text("Uso: /search <título o autor>")
        return
    await _do_search(update, context, query)


async def text_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    if text:
        await _do_search(update, context, text)


async def _do_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str,
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return

    registry: ProviderRegistry = context.application.bot_data["providers"]
    provider_key, clean_query = _split_provider_query(query, registry)
    msg = update.effective_message
    await msg.chat.send_action(ChatAction.TYPING)
    scope = dict(zip(registry.keys, registry.labels, strict=True)).get(
        provider_key,
        "todos los proveedores",
    )
    status = await msg.reply_text(f"Buscando en {scope}…")
    books, errors = await registry.search(
        clean_query,
        settings.max_results,
        provider_key,
    )

    context.user_data["results"] = books
    if not books:
        suffix = f"\nProblemas: {'; '.join(errors)}" if errors else ""
        await status.edit_text(f"No encontré resultados.{suffix}")
        return

    lines = [f"Resultados para: {clean_query}", ""]
    keyboard: list[list[InlineKeyboardButton]] = []
    for idx, book in enumerate(books, start=1):
        lines.append(
            f"{idx}. [{book.source_label}] {book.title} — {book.author_text}"
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{idx}. {book.title[:45]}",
                    callback_data=f"book:{idx - 1}",
                )
            ]
        )
    await status.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def book_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return

    query = update.callback_query
    await query.answer()
    try:
        idx = int(query.data.split(":", 1)[1])
        books: list[BookResult] = context.user_data.get("results", [])
        book = books[idx]
    except (ValueError, IndexError):
        await query.edit_message_text(
            "Ese resultado ya no está disponible. Haz una nueva búsqueda."
        )
        return

    downloads = preferred_downloads(book)
    keyboard: list[list[InlineKeyboardButton]] = []
    for d_idx, (label, url) in enumerate(downloads[:4]):
        if is_allowed_download_url(url):
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"Descargar {label}",
                        callback_data=f"dl:{idx}:{d_idx}",
                    )
                ]
            )

    language = ", ".join(book.languages) if book.languages else "n/d"
    text = (
        f"📖 {book.title}\n"
        f"Autor: {book.author_text}\n"
        f"Idioma: {language}\n"
        f"Fuente: {book.source_label}"
    )
    if not keyboard:
        text += "\n\nNo hay una descarga automática permitida para este resultado."
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


async def _download_with_validated_redirects(
    url: str,
    target: Path,
    max_bytes: int,
) -> None:
    current = url
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=False,
        headers={"User-Agent": "ebook-telegram-bot/0.2"},
    ) as client:
        for _ in range(5):
            if not is_allowed_download_url(current):
                raise ValueError("URL no permitida")
            async with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirección sin Location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                total = 0
                with target.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError("Archivo demasiado grande")
                        handle.write(chunk)
                return
    raise ValueError("Demasiadas redirecciones")


async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return

    query = update.callback_query
    await query.answer("Preparando archivo…")
    try:
        _, book_idx_s, download_idx_s = query.data.split(":")
        book_idx = int(book_idx_s)
        download_idx = int(download_idx_s)
        books: list[BookResult] = context.user_data.get("results", [])
        book = books[book_idx]
        label, url = preferred_downloads(book)[download_idx]
    except (ValueError, IndexError):
        await query.message.reply_text("Ese enlace expiró. Haz una nueva búsqueda.")
        return

    if not is_allowed_download_url(url):
        await query.message.reply_text("El origen del archivo no está permitido.")
        return

    await query.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    suffix = {
        "EPUB": ".epub",
        "PDF": ".pdf",
        "TXT": ".txt",
        "HTML": ".html",
    }.get(label, ".bin")
    safe_name = sanitize_filename(book.title, suffix)
    max_bytes = settings.max_download_mb * 1024 * 1024

    try:
        with tempfile.TemporaryDirectory(prefix="ebookbot-") as temp_dir:
            target = Path(temp_dir) / safe_name
            await _download_with_validated_redirects(url, target, max_bytes)
            with target.open("rb") as handle:
                await query.message.reply_document(
                    document=handle,
                    filename=safe_name,
                    caption=f"{book.title} — {book.author_text}",
                )
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.warning("Download failed: %s", exc)
        await query.message.reply_text("No pude descargar ese archivo de forma segura.")


async def upload_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return
    document = update.effective_message.document
    if not document or not update.effective_user:
        return

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if document.file_size and document.file_size > max_bytes:
        await update.effective_message.reply_text(
            f"Ese archivo supera el límite de subida configurado ({settings.max_upload_mb} MB)."
        )
        return

    library: PersonalLibrary = context.application.bot_data["library"]
    target = library.destination(
        update.effective_user.id,
        document.file_name or "document.bin",
    )
    tg_file = await document.get_file()
    await tg_file.download_to_drive(custom_path=target)
    await update.effective_message.reply_text(
        f"Guardado en tu biblioteca privada: {target.name}\n"
        "Úsalo solo para archivos que tengas derecho a almacenar."
    )


async def list_library(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return
    if not update.effective_user:
        return
    library: PersonalLibrary = context.application.bot_data["library"]
    files = library.list_files(update.effective_user.id)
    if not files:
        await update.effective_message.reply_text("Tu biblioteca está vacía.")
        return
    text = ["📁 Tu biblioteca:"]
    for idx, path in enumerate(files, start=1):
        size_mb = path.stat().st_size / (1024 * 1024)
        text.append(f"{idx}. {path.name} ({size_mb:.1f} MB)")
    await update.effective_message.reply_text("\n".join(text))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error", exc_info=context.error)


def build_application(settings: Settings) -> Application:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .rate_limiter(AIORateLimiter())
        .post_init(post_init)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["providers"] = build_registry(
        enabled=settings.enabled_providers,
        gutendex_base_url=settings.gutendex_base_url,
        search_languages=settings.search_languages,
        libgen_metadata_db=settings.libgen_metadata_db,
        libgen_live_mirrors=settings.libgen_live_mirrors,
    )
    application.bot_data["library"] = PersonalLibrary(settings.data_dir)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("whoami", whoami))
    application.add_handler(CommandHandler("search", search_cmd))
    application.add_handler(CommandHandler("providers", providers_cmd))
    application.add_handler(CommandHandler("library", list_library))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CallbackQueryHandler(book_callback, pattern=r"^book:\d+$"))
    application.add_handler(
        CallbackQueryHandler(download_callback, pattern=r"^dl:\d+:\d+$")
    )
    application.add_handler(MessageHandler(filters.Document.ALL, upload_document))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_search)
    )
    application.add_error_handler(error_handler)
    return application
