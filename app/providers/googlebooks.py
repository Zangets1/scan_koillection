"""Google Books : filet de sécurité, volontairement interrogé en dernier.

Ses notices francophones sont souvent incomplètes ou fausses (éditeur manquant,
pagination erronée). Il n'est utilisé que pour combler les champs encore vides
après la BnF et OpenLibrary, et peut être retiré de ``PROVIDERS``.
"""

from __future__ import annotations

import re

import httpx

from ..models import BookMeta
from .base import Provider, clean_text, dedupe

URL = "https://www.googleapis.com/books/v1/volumes"


class GoogleBooksProvider(Provider):
    name = "googlebooks"
    label = "Google Books"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    async def fetch(self, client: httpx.AsyncClient, isbn13: str) -> BookMeta | None:
        params: dict[str, str] = {"q": f"isbn:{isbn13}", "maxResults": "1"}
        if self.api_key:
            params["key"] = self.api_key
        response = await client.get(URL, params=params)
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        items = payload.get("items") or []
        if not items:
            return None

        info = items[0].get("volumeInfo") or {}
        meta = BookMeta(isbn13=isbn13, sources=["googlebooks"])
        meta.title = clean_text(info.get("title")) or ""
        if not meta.title:
            return None
        meta.subtitle = clean_text(info.get("subtitle"))
        meta.authors = dedupe([clean_text(a) or "" for a in info.get("authors", []) if a])
        meta.publisher = clean_text(info.get("publisher"))
        meta.published_date = _normalize_date(info.get("publishedDate"))
        pages = info.get("pageCount")
        if isinstance(pages, int) and 0 < pages < 20000:
            meta.page_count = pages
        meta.genres = dedupe([clean_text(c) or "" for c in info.get("categories", []) if c])[:6]
        meta.synopsis = clean_text(info.get("description"))
        meta.language = info.get("language")
        links = info.get("imageLinks") or {}
        cover = links.get("thumbnail") or links.get("smallThumbnail")
        if cover:
            meta.cover_url = cover.replace("http://", "https://").replace("&edge=curl", "")
        meta.source_url = info.get("infoLink")
        return meta


def _normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) or re.fullmatch(r"\d{4}-\d{2}", text):
        return text
    match = re.search(r"(1[0-9]{3}|20[0-9]{2})", text)
    return match.group(1) if match else None
