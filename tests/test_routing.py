"""Le routage par groupe d'ISBN : quels catalogues sont interrogés, et lesquels ne le sont pas."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import isbn as isbn_utils
from app.config import Settings
from app.lookup import LookupService
from app.models import BookMeta
from app.providers.base import Provider


class _Recording(Provider):
    """Fournisseur qui note s'il a été appelé, sans toucher au réseau."""

    def __init__(self, name: str, groups: frozenset[str] | None) -> None:
        self.name = name
        self.label = name
        self.groups = groups
        self.calls: list[str] = []

    async def fetch(self, client, isbn13: str) -> BookMeta | None:
        self.calls.append(isbn13)
        return BookMeta(isbn13=isbn13, title=f"Titre {self.name}", sources=[self.name])


# ----------------------------------------------------------------------
# Lecture du groupe d'enregistrement
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("isbn13", "expected"),
    [
        # L'aire anglophone est un seul groupe : rien ne distingue le
        # Royaume-Uni des États-Unis, et les deux préfixes portent les deux.
        ("9780747532743", "en"),  # Bloomsbury, Londres
        ("9780590353403", "en"),  # Scholastic, New York
        ("9781408855652", "en"),  # Bloomsbury, Londres
        ("9781501142970", "en"),  # Simon & Schuster, New York
        ("9798385017577", "en"),  # groupe 979-8, États-Unis
        # Francophonie
        ("9782070643028", "fr"),
        ("9791032403402", "fr"),  # groupe 979-10, France
        # Autres aires
        ("9784088725093", "ja"),
        ("9783442267743", "de"),
        ("9788432296970", "es"),
        # Groupe non répertorié : on ne se prononce pas
        ("9789601234564", ""),
    ],
)
def test_registration_group(isbn13: str, expected: str) -> None:
    assert isbn_utils.registration_group(isbn13) == expected


def test_registration_group_tolerates_hyphens() -> None:
    assert isbn_utils.registration_group("978-2-07-064302-8") == "fr"


def test_long_prefixes_win_over_short_ones() -> None:
    """« 979-10 » est la France, pas un préfixe anglophone mal découpé."""
    assert isbn_utils.registration_group("9791032403402") == "fr"
    assert isbn_utils.registration_group("9798385017577") == "en"


# ----------------------------------------------------------------------
# Arbitrage d'un fournisseur
# ----------------------------------------------------------------------
def test_provider_without_groups_answers_everywhere() -> None:
    """Le comportement par défaut est inchangé : qui ne dit rien est interrogé."""
    provider = _Recording("partout", None)
    assert provider.handles("fr")
    assert provider.handles("en")
    assert provider.handles("")


def test_provider_declines_foreign_group() -> None:
    provider = _Recording("francais", frozenset({"fr"}))
    assert provider.handles("fr")
    assert not provider.handles("en")


def test_unknown_group_never_excludes_anyone() -> None:
    """Sur un ISBN au groupe non répertorié, mieux vaut demander à tout le monde."""
    provider = _Recording("francais", frozenset({"fr"}))
    assert provider.handles("")


# ----------------------------------------------------------------------
# Effet dans le service de recherche
# ----------------------------------------------------------------------
@pytest.fixture
def service() -> LookupService:
    settings = Settings()
    settings.providers = []
    svc = LookupService(settings)
    svc._client = object()  # les faux fournisseurs ne s'en servent pas
    return svc


async def test_english_isbn_skips_french_and_japanese_catalogues(service: LookupService) -> None:
    bnf = _Recording("bnf", frozenset({"fr"}))
    openbd = _Recording("openbd", frozenset({"ja"}))
    partout = _Recording("openlibrary", None)
    service.providers = [bnf, openbd, partout]

    result = await service.lookup("9780747532743", use_cache=False)

    assert bnf.calls == []
    assert openbd.calls == []
    assert partout.calls == ["9780747532743"]
    # Un fournisseur écarté ne doit pas être signalé comme défaillant :
    # il n'apparaît simplement pas dans le rapport.
    assert set(result.providers) == {"openlibrary"}
    assert result.found


async def test_french_isbn_still_queries_the_bnf(service: LookupService) -> None:
    bnf = _Recording("bnf", frozenset({"fr"}))
    openbd = _Recording("openbd", frozenset({"ja"}))
    service.providers = [bnf, openbd]

    await service.lookup("9782070643028", use_cache=False)

    assert bnf.calls == ["9782070643028"]
    assert openbd.calls == []


async def test_japanese_isbn_reaches_openbd(service: LookupService) -> None:
    openbd = _Recording("openbd", frozenset({"ja"}))
    service.providers = [openbd]

    await service.lookup("9784088725093", use_cache=False)

    assert openbd.calls == ["9784088725093"]


async def test_every_provider_filtered_out_is_not_a_crash(service: LookupService) -> None:
    """Si aucun catalogue ne couvre l'aire, on répond « inconnu », pas une erreur."""
    service.providers = [_Recording("openbd", frozenset({"ja"}))]

    result = await service.lookup("9780747532743", use_cache=False)

    assert not result.found
    assert result.providers == {}
    assert result.message
