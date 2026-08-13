"""openBD : base ouverte des livres japonais (ISBN 978-4…).

Indispensable pour les éditions originales de mangas, que ni la BnF ni
OpenLibrary ne référencent correctement.
"""

from __future__ import annotations

import re

import httpx

from ..models import BookMeta
from ..series import parse_volume
from .base import Provider, clean_text

URL = "https://api.openbd.jp/v1/get"


class OpenBdProvider(Provider):
    name = "openbd"
    label = "openBD (Japon)"
    #: La base ne contient que des ISBN japonais. Ce filtre remplace le test
    #: ``startswith("9784")`` qui était écrit ici en dur : le service n'est
    #: désormais plus sollicité du tout hors du Japon.
    groups = frozenset({"ja"})

    async def fetch(self, client: httpx.AsyncClient, isbn13: str) -> BookMeta | None:
        response = await client.get(URL, params={"isbn": isbn13})
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        if not payload or not isinstance(payload, list) or not payload[0]:
            return None

        record = payload[0]
        summary = record.get("summary") or {}
        onix = record.get("onix") or {}

        meta = BookMeta(isbn13=isbn13, sources=["openbd"])
        meta.title = clean_text(summary.get("title")) or ""
        if not meta.title:
            return None
        meta.authors = [a for a in [clean_text(summary.get("author"))] if a]
        meta.publisher = clean_text(summary.get("publisher"))
        meta.published_date = _normalize_date(summary.get("pubdate"))
        meta.cover_url = summary.get("cover") or None
        meta.language = "Japonais"
        meta.series = clean_text(summary.get("series")) or None
        meta.volume = parse_volume(summary.get("volume")) or parse_volume(meta.title)
        meta.synopsis = _extract_description(onix)
        meta.source_url = f"https://openbd.jp/?isbn={isbn13}"
        return meta


def _extract_description(onix: dict) -> str | None:
    contents = ((onix.get("CollateralDetail") or {}).get("TextContent")) or []
    # TextType 03 = description longue, 02 = résumé court, 04 = table des matières.
    for wanted in ("03", "02"):
        for entry in contents:
            if entry.get("TextType") == wanted:
                return clean_text(entry.get("Text"))
    return None


def _normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(digits) >= 6:
        return f"{digits[:4]}-{digits[4:6]}"
    return digits[:4] or None
