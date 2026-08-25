from __future__ import annotations

import logging

from .app import build_application
from .config import Settings


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    application = build_application(settings)
    application.run_polling(drop_pending_updates=True, allowed_updates=None)


if __name__ == "__main__":
    main()
