"""ISBNdb : source commerciale optionnelle (nécessite ``ISBNDB_API_KEY``).

Désactivée tant qu'aucune clé n'est fournie.
"""

from __future__ import annotations

import re

import httpx

from ..models import BookMeta
from .base import Provider, clean_text, dedupe

URL = "https://api2.isbndb.com/book"


class IsbndbProvider(Provider):
    name = "isbndb"
    label = "ISBNdb"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    def enabled(self) -> bool:
        return bool(self.api_key)

    async def fetch(self, client: httpx.AsyncClient, isbn13: str) -> BookMeta | None:
        response = await client.get(
            f"{URL}/{isbn13}", headers={"Authorization": self.api_key}
        )
        if response.status_code != 200:
            return None
        try:
            book = (response.json() or {}).get("book") or {}
        except ValueError:
            return None
        if not book:
            return None

        meta = BookMeta(isbn13=isbn13, sources=["isbndb"])
        meta.title = clean_text(book.get("title")) or ""
        if not meta.title:
            return None
        meta.authors = dedupe([clean_text(a) or "" for a in book.get("authors", []) if a])
        meta.publisher = clean_text(book.get("publisher"))
        meta.published_date = _normalize_date(book.get("date_published"))
        pages = book.get("pages")
        if isinstance(pages, int) and 0 < pages < 20000:
            meta.page_count = pages
        meta.subjects = dedupe([clean_text(s) or "" for s in book.get("subjects", []) if s])[:6]
        meta.synopsis = clean_text(book.get("synopsis") or book.get("overview"))
        meta.language = book.get("language")
        meta.cover_url = book.get("image")
        return meta


def _normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    match = re.search(r"(1[0-9]{3}|20[0-9]{2})", text)
    return match.group(1) if match else None
