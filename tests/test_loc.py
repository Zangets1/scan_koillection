"""Fournisseur Library of Congress.

Le port 210 étant filtré sur la machine d'intégration continue comme sur celle
de développement, ces tests ne peuvent pas rejouer une réponse capturée du
service. La charge utile employée est une notice MARC21 réelle d'un livre
américain, empruntée aux fixtures de K10plus : les deux catalogues parlent le
même format dans la même enveloppe SRU, et ce qui est vérifié ici est le
comportement du fournisseur, pas les octets exacts de la LC.

Ce qui reste non couvert par des tests, faute d'accès : la syntaxe de requête
elle-même. Elle a été validée à la main depuis un réseau où le port passe —
`tools/mesure-loc.py` a trouvé 10 notices sur 55 ISBN anglophones.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.providers import build_providers
from app.providers.loc import LocProvider

FIXTURES = Path(__file__).parent / "fixtures"


def notice_americaine() -> str:
    return (FIXTURES / "k10plus_etats_unis.xml").read_text(encoding="utf-8")


def reponse_vide() -> str:
    return (FIXTURES / "k10plus_vide.xml").read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# Ce que le fournisseur retient
# ----------------------------------------------------------------------
async def test_reads_an_american_record() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "lx2.loc.gov"
        assert request.url.port == 210
        assert request.url.params["query"] == "bath.isbn=9780307700001"
        return httpx.Response(200, text=notice_americaine())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        meta = await LocProvider().fetch(client, "9780307700001")

    assert meta is not None
    assert meta.title == "The Buddha in the attic"
    assert meta.authors == ["Julie Otsuka"]
    assert meta.publisher == "Alfred A. Knopf"
    assert meta.page_count == 129
    assert meta.country == "États-Unis"


async def test_drops_english_subject_headings() -> None:
    """Les vedettes LCSH indexent, elles ne décrivent pas un genre lisible."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=notice_americaine()))
    ) as client:
        meta = await LocProvider().fetch(client, "9780307700001")

    assert meta is not None
    assert meta.synopsis is None
    assert meta.genres == []
    assert meta.subjects == []
    assert meta.source_url and meta.source_url.startswith("https://catalog.loc.gov/")


async def test_returns_none_when_unknown() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=reponse_vide()))
    ) as client:
        assert await LocProvider().fetch(client, "9780345391803") is None


async def test_raises_on_server_error() -> None:
    """L'erreur remonte : LookupService la traduit en « injoignable »."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await LocProvider().fetch(client, "9780307700001")


async def test_one_request_per_lookup() -> None:
    """Elle ne possède que 18 % des ISBN anglophones : tenter une seconde forme
    doublerait le temps de réponse quatre fois sur cinq pour rien."""
    appels = []

    async def handler(request: httpx.Request) -> httpx.Response:
        appels.append(str(request.url))
        return httpx.Response(200, text=reponse_vide())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await LocProvider().fetch(client, "9780345391803")

    assert len(appels) == 1


# ----------------------------------------------------------------------
# Elle ne s'active qu'à la demande
# ----------------------------------------------------------------------
def test_absent_from_the_default_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Son port est filtré chez beaucoup : l'activer d'office ferait attendre
    LOOKUP_DEADLINE à chaque scan anglophone."""
    monkeypatch.delenv("PROVIDERS", raising=False)
    noms = [p.name for p in build_providers(Settings())]
    assert "loc" not in noms


def test_activated_by_naming_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDERS", "bnf,openlibrary,loc")
    noms = [p.name for p in build_providers(Settings())]
    assert noms == ["bnf", "openlibrary", "loc"]


def test_english_area_only() -> None:
    provider = LocProvider()
    assert provider.handles("en")
    assert not provider.handles("fr")
    assert not provider.handles("ja")
