"""Journal local des livres ajoutés (historique + détection de doublon rapide)."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS additions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    isbn13       TEXT NOT NULL,
    title        TEXT NOT NULL,
    authors      TEXT NOT NULL DEFAULT '',
    series       TEXT NOT NULL DEFAULT '',
    volume       INTEGER,
    collection   TEXT NOT NULL DEFAULT '',
    item_id      TEXT NOT NULL DEFAULT '',
    item_url     TEXT NOT NULL DEFAULT '',
    read         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_additions_isbn ON additions (isbn13);
"""


class History:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_sync(self) -> None:
        try:
            with self._connect() as connection:
                connection.executescript(SCHEMA)
        except (sqlite3.OperationalError, OSError) as exc:
            # Cas classique sur NAS : le volume monté appartient à root alors que
            # le conteneur tourne sans privilèges.
            raise RuntimeError(
                f"Impossible d'écrire l'historique dans {self.path.parent} ({exc}). "
                f"Donnez les droits au conteneur, par exemple « chown -R 10001:10001 ./data », "
                f"ou ajustez PUID/PGID."
            ) from exc

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _record_sync(self, entry: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO additions
                    (isbn13, title, authors, series, volume, collection,
                     item_id, item_url, read, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.get("isbn13", ""),
                    entry.get("title", ""),
                    entry.get("authors", ""),
                    entry.get("series", "") or "",
                    entry.get("volume"),
                    entry.get("collection", ""),
                    entry.get("item_id", ""),
                    entry.get("item_url", ""),
                    1 if entry.get("read") else 0,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )

    async def record(self, entry: dict) -> None:
        await asyncio.to_thread(self._record_sync, entry)

    def _recent_sync(self, limit: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM additions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    async def recent(self, limit: int = 30) -> list[dict]:
        return await asyncio.to_thread(self._recent_sync, limit)

    def _find_sync(self, isbn13: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM additions WHERE isbn13 = ? ORDER BY id DESC LIMIT 1", (isbn13,)
            ).fetchone()
        return dict(row) if row else None

    async def find(self, isbn13: str) -> dict | None:
        return await asyncio.to_thread(self._find_sync, isbn13)
