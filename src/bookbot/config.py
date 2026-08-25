from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re


_LANGUAGE_CODE = re.compile(r"^[a-z]{2}$")


def _csv_ints(value: str) -> frozenset[int]:
    if not value.strip():
        return frozenset()
    values: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            values.add(int(part))
    return frozenset(values)


def _csv_strings(value: str) -> tuple[str, ...]:
    out: list[str] = []
    for part in value.split(","):
        item = part.strip()
        if item and item not in out:
            out.append(item)
    return tuple(out)


def _language_codes(value: str) -> tuple[str, ...]:
    codes: list[str] = []
    invalid: list[str] = []
    for part in value.split(","):
        code = part.strip().lower()
        if not code:
            continue
        if not _LANGUAGE_CODE.fullmatch(code):
            invalid.append(code)
            continue
        if code not in codes:
            codes.append(code)
    if invalid:
        raise RuntimeError(
            "SEARCH_LANGUAGES must contain comma-separated two-letter language codes; "
            f"invalid: {', '.join(invalid)}"
        )
    return tuple(codes)


def _provider_keys(value: str) -> tuple[str, ...]:
    supported = {"gutenberg", "libgen"}
    out: list[str] = []
    unknown: list[str] = []
    for part in value.split(","):
        key = part.strip().lower()
        if not key:
            continue
        if key not in supported:
            unknown.append(key)
            continue
        if key not in out:
            out.append(key)
    if unknown:
        raise RuntimeError(
            f"Unsupported provider(s) in ENABLED_PROVIDERS: {', '.join(unknown)}"
        )
    return tuple(out) or ("gutenberg",)


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    allowed_user_ids: frozenset[int]
    data_dir: Path
    max_results: int
    max_download_mb: int
    max_upload_mb: int
    log_level: str
    gutendex_base_url: str
    enabled_providers: tuple[str, ...]
    search_languages: tuple[str, ...]
    libgen_metadata_db: Path
    libgen_live_mirrors: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

        max_results = min(max(int(os.getenv("MAX_RESULTS", "8")), 1), 10)
        max_download_mb = min(max(int(os.getenv("MAX_DOWNLOAD_MB", "48")), 1), 49)
        max_upload_mb = min(max(int(os.getenv("MAX_UPLOAD_MB", "19")), 1), 19)
        data_dir = Path(os.getenv("DATA_DIR", "/data"))

        return cls(
            telegram_bot_token=token,
            allowed_user_ids=_csv_ints(os.getenv("ALLOWED_USER_IDS", "")),
            data_dir=data_dir,
            max_results=max_results,
            max_download_mb=max_download_mb,
            max_upload_mb=max_upload_mb,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            gutendex_base_url=os.getenv(
                "GUTENDEX_BASE_URL", "https://gutendex.com"
            ).rstrip("/"),
            enabled_providers=_provider_keys(
                os.getenv("ENABLED_PROVIDERS", "gutenberg")
            ),
            search_languages=_language_codes(os.getenv("SEARCH_LANGUAGES", "")),
            libgen_metadata_db=Path(
                os.getenv(
                    "LIBGEN_METADATA_DB",
                    str(data_dir / "libgen-metadata.sqlite3"),
                )
            ),
            libgen_live_mirrors=_csv_strings(
                os.getenv("LIBGEN_LIVE_MIRRORS", "")
            ),
        )
