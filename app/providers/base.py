"""Socle commun aux fournisseurs de métadonnées."""

from __future__ import annotations

import abc
import logging

import httpx

from ..models import BookMeta

logger = logging.getLogger(__name__)


class Provider(abc.ABC):
    """Un fournisseur interroge un catalogue et renvoie des métadonnées normalisées."""

    #: Identifiant utilisé dans la variable d'environnement ``PROVIDERS``
    name: str = ""
    #: Libellé affiché dans l'interface
    label: str = ""

    def enabled(self) -> bool:  # pragma: no cover - trivial
        return True

    @abc.abstractmethod
    async def fetch(self, client: httpx.AsyncClient, isbn13: str) -> BookMeta | None:
        """Renvoie les métadonnées, ou ``None`` si le catalogue ne connaît pas l'ISBN."""


def clean_text(value: str | None) -> str | None:
    """Nettoie les espaces multiples et la ponctuation ISBD résiduelle."""
    if not value:
        return None
    text = " ".join(str(value).split())
    text = text.strip(" /:;,.-–—")
    return text or None


def dedupe(values: list[str]) -> list[str]:
    """Déduplique en conservant l'ordre et en ignorant la casse."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result
