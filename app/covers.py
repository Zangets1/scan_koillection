"""Résolution des couvertures.

Les services de couverture ne renvoient pas 404 quand l'image n'existe pas :
la BnF répond 500 avec une page HTML, OpenLibrary répond 200 avec un GIF
transparent de 43 octets. On teste donc réellement chaque candidat avant de
l'afficher ou de le téléverser dans Koillection.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

#: En dessous, il s'agit d'un pixel de remplissage et non d'une couverture.
MIN_COVER_BYTES = 2000
MAX_COVER_BYTES = 8 * 1024 * 1024

#: L'URL de couverture transite par le navigateur : sans liste blanche, le
#: service deviendrait un relais HTTP ouvert vers le réseau interne du NAS.
ALLOWED_HOSTS = {
    "catalogue.bnf.fr",
    "covers.openlibrary.org",
    "openbd.jp",
    "cover.openbd.jp",
    "books.google.com",
    "books.googleusercontent.com",
    "images.isbndb.com",
}


def is_allowed(url: str) -> bool:
    """Vrai si l'URL pointe vers un service de couverture connu."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in ALLOWED_HOSTS or any(host.endswith(f".{h}") for h in ALLOWED_HOSTS)


class Cover:
    def __init__(self, content: bytes, content_type: str, url: str) -> None:
        self.content = content
        self.content_type = content_type
        self.url = url

    @property
    def extension(self) -> str:
        return {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/avif": ".avif",
        }.get(self.content_type, ".jpg")


async def resolve(client: httpx.AsyncClient, candidates: list[str]) -> Cover | None:
    """Renvoie la première couverture réellement exploitable."""
    for url in candidates:
        if not url or not is_allowed(url):
            continue
        try:
            response = await client.get(url, timeout=10.0)
        except httpx.HTTPError as exc:
            logger.info("Couverture injoignable (%s) : %s", url, exc)
            continue
        if response.status_code != 200:
            continue
        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            continue
        content = response.content
        if not MIN_COVER_BYTES <= len(content) <= MAX_COVER_BYTES:
            continue
        if content_type == "image/gif":
            # OpenLibrary sert un GIF transparent en guise de « pas de couverture ».
            continue
        return Cover(content, content_type, url)
    return None
