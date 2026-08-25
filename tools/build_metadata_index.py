#!/usr/bin/env python3
"""Build a small local FTS metadata index from a CSV you already possess.

This utility imports bibliographic metadata only. It deliberately ignores mirror,
MD5, locator, torrent, and download-link fields.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sqlite3
import sys


def _pick(row: dict[str, str], *names: str) -> str:
    lowered = {key.lower().strip(): (value or "").strip() for key, value in row.items() if key}
    for name in names:
        value = lowered.get(name.lower(), "")
        if value:
            return value
    return ""


def build_index(source_csv: Path, target_db: Path) -> int:
    target_db.parent.mkdir(parents=True, exist_ok=True)
    if target_db.exists():
        target_db.unlink()

    connection = sqlite3.connect(target_db)
    inserted = 0
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE libgen_book USING fts5(title, author, language)"
        )
        with source_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("CSV must contain a header row")
            for row in reader:
                title = _pick(row, "title")
                if not title:
                    continue
                author = _pick(row, "author", "authors")
                language = _pick(row, "language", "lang")
                connection.execute(
                    "INSERT INTO libgen_book(title, author, language) VALUES (?, ?, ?)",
                    (title, author, language),
                )
                inserted += 1
                if inserted % 10_000 == 0:
                    connection.commit()
        connection.commit()
        connection.execute("INSERT INTO libgen_book(libgen_book) VALUES('optimize')")
        connection.commit()
    finally:
        connection.close()
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_csv", type=Path, help="CSV metadata file you already possess")
    parser.add_argument("target_db", type=Path, help="Output SQLite file")
    args = parser.parse_args()

    if not args.source_csv.is_file():
        parser.error(f"source CSV not found: {args.source_csv}")

    try:
        count = build_index(args.source_csv, args.target_db)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Imported {count} metadata records into {args.target_db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
