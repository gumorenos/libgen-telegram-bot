from __future__ import annotations

from pathlib import Path
import sys
import time

HEARTBEAT = Path("/tmp/bookbot-heartbeat")
MAX_AGE_SECONDS = 75


def main() -> int:
    try:
        age = time.time() - HEARTBEAT.stat().st_mtime
    except FileNotFoundError:
        return 1
    return 0 if age <= MAX_AGE_SECONDS else 1


if __name__ == "__main__":
    sys.exit(main())
