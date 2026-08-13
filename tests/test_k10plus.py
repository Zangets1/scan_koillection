"""Lecture MARC21 et fournisseur K10plus, sur de vraies notices capturées."""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.providers import marc21
from app.providers.k10plus import K10plusProvider

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# Analyse d'une notice MARC21
# ----------------------------------------------------------------------
def test_reads_a_british_record() -> None:
    meta = marc21.parse_sru(fixture("k10plus_harry_potter.xml"), "9780747532743", "k10plus")

    assert meta is not None
    assert meta.title == "Harry Potter and the philosopher's stone"
    assert meta.authors == ["J. K. Rowling"]
    assert meta.publisher == "Bloomsbury"
    assert meta.published_date == "1997"
    assert meta.page_count == 223
    assert meta.language == "Anglais"


def test_reads_an_american_record() -> None:
    meta = marc21.parse_sru(fixture("k10plus_etats_unis.xml"), "9780307700001", "k10plus")

    assert meta is not None
    assert meta.title == "The Buddha in the attic"
    assert meta.authors == ["Julie Otsuka"]
    assert meta.publisher == "Alfred A. Knopf"


def test_initials_keep_their_final_dot() -> None:
    """« J. K. » ne doit pas ressortir en « J. K » : clean_text mangerait le point."""
    assert marc21._flip("Rowling, J. K.") == "J. K. Rowling"
    assert marc21._flip("Tolkien, J. R. R., 1892-1973") == "J. R. R. Tolkien"


def test_no_record_gives_none() -> None:
    assert marc21.parse_sru(fixture("k10plus_vide.xml"), "9791032403402", "k10plus") is None


def test_malformed_xml_gives_none() -> None:
    assert marc21.parse_sru("<pas/vraiment>du xml", "9780747532743", "k10plus") is None


# ----------------------------------------------------------------------
# Le pays d'édition : lu dans la notice, jamais déduit de l'ISBN
# ----------------------------------------------------------------------
def test_two_isbn_of_the_same_group_give_two_countries() -> None:
    """La démonstration du problème : « 978-0 » ne dit rien du pays.

    Ces deux ISBN partagent le même groupe d'enregistrement. Seule la notice
    permet de savoir que l'un a été publié à Londres et l'autre à New York.
    """
    british = marc21.parse_sru(fixture("k10plus_harry_potter.xml"), "9780747532743", "k10plus")
    american = marc21.parse_sru(fixture("k10plus_etats_unis.xml"), "9780307700001", "k10plus")

    assert british is not None and american is not None
    assert british.isbn13.startswith("9780")
    assert american.isbn13.startswith("9780")
    assert british.country == "Royaume-Uni"
    assert american.country == "États-Unis"


@pytest.mark.parametrize(
    ("code", "expected"),
    [("enk", "Royaume-Uni"), ("xxk", "Royaume-Uni"), ("xxu", "États-Unis"),
     ("nyu", "États-Unis"), ("fr", "France"), ("ja", "Japon"), ("zzz", None)],
)
def test_marc_country_codes(code: str, expected: str | None) -> None:
    xml = (
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        f'<controlfield tag="008">041105s2000    {code:<3}|||||      00| ||eng c</controlfield>'
        '<datafield tag="245" ind1="1" ind2="0"><subfield code="a">Un titre</subfield></datafield>'
        "</record>"
    )
    meta = marc21.parse(marc21.Record(ET.fromstring(xml)), "9780000000000", "k10plus")
    assert meta is not None
    assert meta.country == expected


def test_iso_country_in_field_044() -> None:
    """Le catalogage allemand préfixe le code ISO d'une zone : « XA-GB »."""
    xml = (
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        '<controlfield tag="008">041105s2000    zzz|||||      00| ||eng c</controlfield>'
        '<datafield tag="044" ind1=" " ind2=" "><subfield code="c">XA-GB</subfield></datafield>'
        '<datafield tag="245" ind1="1" ind2="0"><subfield code="a">Un titre</subfield></datafield>'
        "</record>"
    )
    meta = marc21.parse(marc21.Record(ET.fromstring(xml)), "9780000000000", "k10plus")
    assert meta is not None
    assert meta.country == "Royaume-Uni"


# ----------------------------------------------------------------------
# Ce que le fournisseur retient — et ce qu'il jette
# ----------------------------------------------------------------------
async def test_provider_drops_summary_and_genres() -> None:
    """Ni « Kinderbuch » ni un résumé allemand n'ont leur place dans une fiche française.

    La langue de ces zones dépend de la bibliothèque qui a rédigé la notice, pas
    du livre : la notice britannique capturée ici les porte en allemand, tandis
    que l'américaine les porte en anglais. Faute de pouvoir trier, on jette.
    """
    # La notice capturée porte bien un résumé et des genres à écarter…
    raw = marc21.parse_sru(fixture("k10plus_harry_potter.xml"), "9780747532743", "k10plus")
    assert raw is not None
    assert raw.synopsis and raw.genres, "la fixture doit contenir du texte à écarter"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["query"] == "pica.isb=9780747532743"
        return httpx.Response(200, text=fixture("k10plus_harry_potter.xml"))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        meta = await K10plusProvider().fetch(client, "9780747532743")

    # …mais le fournisseur ne garde que le factuel.
    assert meta is not None
    assert meta.synopsis is None
    assert meta.genres == []
    assert meta.subjects == []
    assert meta.page_count == 223
    assert meta.publisher == "Bloomsbury"
    assert meta.country == "Royaume-Uni"
    assert meta.source_url and meta.source_url.endswith("9780747532743")


async def test_provider_returns_none_when_unknown() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=fixture("k10plus_vide.xml"))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert await K10plusProvider().fetch(client, "9791032403402") is None


async def test_provider_raises_on_server_error() -> None:
    """Une erreur serveur remonte : LookupService la traduit en « injoignable »."""
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await K10plusProvider().fetch(client, "9780747532743")


def test_provider_stays_out_of_the_french_area() -> None:
    """Mesure faite, il ne comble aucun champ sur un ISBN 978-2 mais coûte une requête."""
    provider = K10plusProvider()
    assert provider.handles("en")
    assert not provider.handles("fr")
    assert not provider.handles("ja")
