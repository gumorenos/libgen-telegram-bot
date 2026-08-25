from __future__ import annotations

from pathlib import Path

from .security import sanitize_filename


class PersonalLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root

    def user_dir(self, user_id: int) -> Path:
        path = self.root / "library" / str(user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def destination(self, user_id: int, filename: str) -> Path:
        return self.user_dir(user_id) / sanitize_filename(filename)

    def list_files(self, user_id: int, limit: int = 20) -> list[Path]:
        files = [p for p in self.user_dir(user_id).iterdir() if p.is_file()]
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
