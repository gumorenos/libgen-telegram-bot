from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _csv_ints(value: str) -> frozenset[int]:
    if not value.strip():
        return frozenset()
    values: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        values.add(int(part))
    return frozenset(values)


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

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

        max_results = min(max(int(os.getenv("MAX_RESULTS", "8")), 1), 10)
        max_download_mb = min(max(int(os.getenv("MAX_DOWNLOAD_MB", "48")), 1), 49)
        max_upload_mb = min(max(int(os.getenv("MAX_UPLOAD_MB", "19")), 1), 19)

        return cls(
            telegram_bot_token=token,
            allowed_user_ids=_csv_ints(os.getenv("ALLOWED_USER_IDS", "")),
            data_dir=Path(os.getenv("DATA_DIR", "/data")),
            max_results=max_results,
            max_download_mb=max_download_mb,
            max_upload_mb=max_upload_mb,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            gutendex_base_url=os.getenv("GUTENDEX_BASE_URL", "https://gutendex.com").rstrip("/"),
        )
