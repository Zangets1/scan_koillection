"""Registre des fournisseurs de métadonnées."""

from __future__ import annotations

from ..config import Settings
from .base import Provider
from .bnf import BnfProvider
from .googlebooks import GoogleBooksProvider
from .isbndb import IsbndbProvider
from .k10plus import K10plusProvider
from .loc import LocProvider
from .openbd import OpenBdProvider
from .openlibrary import OpenLibraryProvider
from .sudoc import SudocProvider

__all__ = [
    "Provider",
    "BnfProvider",
    "GoogleBooksProvider",
    "IsbndbProvider",
    "K10plusProvider",
    "LocProvider",
    "OpenBdProvider",
    "OpenLibraryProvider",
    "SudocProvider",
    "build_providers",
]


def build_providers(settings: Settings) -> list[Provider]:
    """Instancie les fournisseurs listés dans ``PROVIDERS``, dans cet ordre.

    L'ordre fait foi : en cas de conflit, la première source qui renseigne un
    champ l'emporte.
    """
    catalogue: dict[str, Provider] = {
        BnfProvider.name: BnfProvider(),
        SudocProvider.name: SudocProvider(),
        OpenLibraryProvider.name: OpenLibraryProvider(),
        K10plusProvider.name: K10plusProvider(),
        LocProvider.name: LocProvider(),
        OpenBdProvider.name: OpenBdProvider(),
        GoogleBooksProvider.name: GoogleBooksProvider(settings.google_books_key),
        IsbndbProvider.name: IsbndbProvider(settings.isbndb_key),
    }
    providers: list[Provider] = []
    for name in settings.providers:
        provider = catalogue.get(name.strip().lower())
        if provider is not None and provider.enabled():
            providers.append(provider)
    return providers
