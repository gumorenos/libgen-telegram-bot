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
from .providers import GutendexProvider, preferred_downloads
from .security import is_allowed_download_url, is_allowed_user, sanitize_filename

logger = logging.getLogger(__name__)


def _auth_message(settings: Settings) -> str:
    if settings.allowed_user_ids:
        return "No autorizado. Usa /whoami y añade tu ID a ALLOWED_USER_IDS en el VPS."
    return "Bot aún sin allowlist. Usa /whoami y configura ALLOWED_USER_IDS antes de usarlo."


async def _require_allowed(update: Update, settings: Settings) -> bool:
    user_id = update.effective_user.id if update.effective_user else None
    if not settings.allowed_user_ids or not is_allowed_user(user_id, settings.allowed_user_ids):
        if update.callback_query:
            await update.callback_query.answer("No autorizado", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text(_auth_message(settings))
        return False
    return True


async def heartbeat_loop() -> None:
    while True:
        HEARTBEAT.write_text(str(time.time()), encoding="utf-8")
        await asyncio.sleep(20)


async def post_init(application: Application) -> None:
    HEARTBEAT.write_text(str(time.time()), encoding="utf-8")
    application.create_task(heartbeat_loop(), name="heartbeat")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return
    await update.effective_message.reply_text(
        "📚 Bot privado de ebooks\n\n"
        "Busca libros de dominio público con /search <texto> o simplemente envía un título/autor.\n"
        "También puedes subir documentos propios (máx. configurado) para guardarlos en tu biblioteca.\n\n"
        "Comandos: /search, /library, /status, /whoami, /help"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    await update.effective_message.reply_text(f"Tu Telegram user ID es: {user.id}")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return

    lines = ["🟢 Bot: OK"]
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        started = time.monotonic()
        try:
            response = await client.get(
                f"{settings.gutendex_base_url}/books",
                params={"search": "don quixote"},
            )
            response.raise_for_status()
            payload = response.json()
            latency_ms = round((time.monotonic() - started) * 1000)
            results = len(payload.get("results", []))
            lines.append(
                f"🟢 Gutendex API: OK — {latency_ms} ms ({results} resultados de prueba)"
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Gutendex status check failed: %s", exc)
            lines.append("🔴 Gutendex API: ERROR")

        try:
            response = await client.get(
                "https://www.gutenberg.org/",
                headers={"User-Agent": "ebook-telegram-bot-status/0.1"},
            )
            response.raise_for_status()
            lines.append("🟢 Project Gutenberg: OK")
        except httpx.HTTPError as exc:
            logger.warning("Project Gutenberg status check failed: %s", exc)
            lines.append("🔴 Project Gutenberg: ERROR")

    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(settings.data_dir)
        free_gb = usage.free / (1024**3)
        lines.append(f"🟢 Biblioteca local: OK — {free_gb:.1f} GB libres")
    except OSError as exc:
        logger.warning("Local library status check failed: %s", exc)
        lines.append("🔴 Biblioteca local: ERROR")

    await update.effective_message.reply_text("\n".join(lines))


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip()
    if not query:
        await update.effective_message.reply_text("Uso: /search título o autor")
        return
    await _do_search(update, context, query)


async def text_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = (update.effective_message.text or "").strip()
    if query:
        await _do_search(update, context, query)


async def _do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return

    provider: GutendexProvider = context.application.bot_data["provider"]
    msg = update.effective_message
    await msg.chat.send_action(ChatAction.TYPING)
    status = await msg.reply_text("Buscando en Project Gutenberg…")
    try:
        books = await provider.search(query, settings.max_results)
    except httpx.HTTPError as exc:
        logger.warning("Search failed: %s", exc)
        await status.edit_text("No pude consultar el catálogo en este momento.")
        return

    context.user_data["results"] = books
    if not books:
        await status.edit_text("No encontré resultados de dominio público.")
        return

    lines = [f"Resultados para: {query}", ""]
    keyboard: list[list[InlineKeyboardButton]] = []
    for idx, book in enumerate(books, start=1):
        lines.append(f"{idx}. {book.title} — {book.author_text}")
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

    language = ", ".join(book.languages) if book.languages else "—"
    count = str(book.download_count) if book.download_count is not None else "—"
    text = (
        f"📖 {book.title}\n"
        f"Autor: {book.author_text}\n"
        f"Idioma: {language}\n"
        f"Descargas en catálogo: {count}\n"
        "Fuente: Project Gutenberg"
    )
    if not keyboard:
        text += "\n\nNo hay un formato descargable permitido para este resultado."
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not await _require_allowed(update, settings):
        return

    query = update.callback_query
    await query.answer("Preparando archivo…")
    try:
        _, book_idx_s, dl_idx_s = query.data.split(":")
        book_idx = int(book_idx_s)
        dl_idx = int(dl_idx_s)
        books: list[BookResult] = context.user_data.get("results", [])
        book = books[book_idx]
        label, url = preferred_downloads(book)[dl_idx]
    except (ValueError, IndexError):
        await query.message.reply_text("El resultado expiró. Haz una nueva búsqueda.")
        return

    if not is_allowed_download_url(url):
        await query.message.reply_text(
            "URL de descarga rechazada por la política de seguridad del bot."
        )
        return

    max_bytes = settings.max_download_mb * 1024 * 1024
    suffix = {
        "EPUB": ".epub",
        "PDF": ".pdf",
        "TXT": ".txt",
        "HTML": ".html",
    }.get(label, ".bin")
    filename = sanitize_filename(f"{book.title}{suffix}")

    await query.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    path: Path | None = None
    response: httpx.Response | None = None
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            current_url = url
            for _ in range(6):
                if not is_allowed_download_url(current_url):
                    raise ValueError("download redirect left the Gutenberg allowlist")
                request = client.build_request("GET", current_url)
                response = await client.send(request, stream=True)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    await response.aclose()
                    response = None
                    if not location:
                        raise httpx.HTTPStatusError(
                            "redirect without location",
                            request=request,
                            response=httpx.Response(502, request=request),
                        )
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                break
            else:
                raise ValueError("too many redirects")

            if response is None:
                raise ValueError("download response missing")

            content_length = int(response.headers.get("content-length", "0") or 0)
            if content_length and content_length > max_bytes:
                await query.message.reply_text(
                    f"El archivo supera el límite configurado de {settings.max_download_mb} MB."
                )
                return

            with tempfile.NamedTemporaryFile(
                prefix="bookbot-",
                suffix=suffix,
                delete=False,
            ) as tmp:
                path = Path(tmp.name)
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        await query.message.reply_text(
                            f"El archivo supera el límite configurado de {settings.max_download_mb} MB."
                        )
                        return
                    tmp.write(chunk)

        if path is None:
            raise ValueError("temporary download missing")
        with path.open("rb") as fh:
            await query.message.reply_document(
                document=fh,
                filename=filename,
                read_timeout=120,
                write_timeout=120,
            )
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Download failed: %s", exc)
        await query.message.reply_text(
            "No pude descargar ese archivo desde Project Gutenberg."
        )
    finally:
        if response is not None:
            await response.aclose()
        if path is not None:
            path.unlink(missing_ok=True)


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
    application.bot_data["provider"] = GutendexProvider(settings.gutendex_base_url)
    application.bot_data["library"] = PersonalLibrary(settings.data_dir)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("whoami", whoami))
    application.add_handler(CommandHandler("search", search_cmd))
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
