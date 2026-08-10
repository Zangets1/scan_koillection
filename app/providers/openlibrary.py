"""OpenLibrary : couverture mondiale, gratuit et sans clé d'API.

Complément utile à la BnF pour les éditions étrangères et les couvertures.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from ..models import BookMeta
from ..series import parse_volume
from .base import Provider, clean_text, dedupe

BASE = "https://openlibrary.org"


class OpenLibraryProvider(Provider):
    name = "openlibrary"
    label = "OpenLibrary"

    async def fetch(self, client: httpx.AsyncClient, isbn13: str) -> BookMeta | None:
        books_task = client.get(
            f"{BASE}/api/books",
            params={"bibkeys": f"ISBN:{isbn13}", "format": "json", "jscmd": "data"},
        )
        edition_task = client.get(f"{BASE}/isbn/{isbn13}.json", follow_redirects=True)
        books_res, edition_res = await asyncio.gather(
            books_task, edition_task, return_exceptions=True
        )

        data = _json_or_none(books_res)
        payload = (data or {}).get(f"ISBN:{isbn13}") if isinstance(data, dict) else None
        edition = _json_or_none(edition_res)

        if not payload and not edition:
            return None

        meta = BookMeta(isbn13=isbn13, sources=["openlibrary"])
        payload = payload or {}
        edition = edition or {}

        meta.title = clean_text(payload.get("title") or edition.get("title")) or ""
        if not meta.title:
            return None
        meta.subtitle = clean_text(payload.get("subtitle") or edition.get("subtitle"))
        meta.authors = dedupe(
            [clean_text(a.get("name")) or "" for a in payload.get("authors", []) if a.get("name")]
        )
        publishers = payload.get("publishers") or []
        if publishers:
            meta.publisher = clean_text(publishers[0].get("name"))
        elif edition.get("publishers"):
            meta.publisher = clean_text(edition["publishers"][0])

        meta.published_date = _normalize_date(
            payload.get("publish_date") or edition.get("publish_date")
        )
        pages = payload.get("number_of_pages") or edition.get("number_of_pages")
        if isinstance(pages, int) and 0 < pages < 20000:
            meta.page_count = pages

        meta.genres = dedupe(
            [clean_text(s.get("name")) or "" for s in payload.get("subjects", []) if s.get("name")]
        )[:6]

        cover = payload.get("cover") or {}
        meta.cover_url = cover.get("large") or cover.get("medium") or (
            f"https://covers.openlibrary.org/b/isbn/{isbn13}-L.jpg"
        )
        meta.source_url = payload.get("url") or (
            f"{BASE}{edition['key']}" if edition.get("key") else None
        )

        series_raw = (edition.get("series") or [None])[0]
        if series_raw:
            meta.series, meta.volume = _split_series_entry(series_raw)

        languages = edition.get("languages") or []
        if languages:
            meta.language = str(languages[0].get("key", "")).rsplit("/", 1)[-1] or None

        # Le résumé n'existe que sur l'« œuvre », pas sur l'édition.
        work_key = ((edition.get("works") or [{}])[0]).get("key")
        if work_key:
            meta.synopsis = await _fetch_description(client, work_key)

        return meta


def _json_or_none(response: object) -> dict | None:
    if isinstance(response, BaseException) or not isinstance(response, httpx.Response):
        return None
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def _fetch_description(client: httpx.AsyncClient, work_key: str) -> str | None:
    try:
        response = await client.get(f"{BASE}{work_key}.json")
    except httpx.HTTPError:
        return None
    work = _json_or_none(response)
    if not work:
        return None
    description = work.get("description")
    if isinstance(description, dict):
        description = description.get("value")
    if not isinstance(description, str):
        return None
    # OpenLibrary colle souvent la source en fin de texte, après un séparateur.
    description = re.split(r"\r?\n-{3,}", description)[0]
    return clean_text(description)


def _split_series_entry(raw: str) -> tuple[str | None, int | None]:
    """« One Piece #12 », « ONE PIECE (1) », « Harry Potter, 3 » → (série, tome)."""
    text = raw.strip()
    for pattern in (
        r"^(?P<series>.+?)\s*[#,]\s*(?P<volume>\d{1,3})\s*$",
        r"^(?P<series>.+?)\s*\(\s*(?P<volume>\d{1,3})\s*\)\s*$",
    ):
        match = re.match(pattern, text)
        if match:
            return clean_text(match.group("series")), parse_volume(match.group("volume"))
    return clean_text(text), None


def _normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.search(r"(1[0-9]{3}|20[0-9]{2})", str(raw))
    return match.group(1) if match else None
