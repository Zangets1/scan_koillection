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
    #: Aires linguistiques (cf. :func:`app.isbn.registration_group`) que ce
    #: catalogue couvre utilement. ``None`` signifie « toutes », ce qui reste le
    #: cas par défaut : un fournisseur qui ne se prononce pas est interrogé comme
    #: auparavant.
    groups: frozenset[str] | None = None

    def enabled(self) -> bool:  # pragma: no cover - trivial
        return True

    def handles(self, group: str) -> bool:
        """Vrai si ce catalogue mérite d'être interrogé pour cette aire.

        Un groupe inconnu (chaîne vide) n'écarte personne : mieux vaut une
        requête de trop qu'une notice manquée sur un ISBN mal identifié.
        """
        return self.groups is None or not group or group in self.groups

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
