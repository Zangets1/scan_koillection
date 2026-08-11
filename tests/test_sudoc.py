"""Analyse des notices UNIMARC du SUDOC (réponses réelles figées en fixtures)."""

from pathlib import Path

import pytest

from app.providers.sudoc import PPN_RE, parse_record

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_serie_et_tome_lus_dans_la_zone_200():
    # Le SUDOC place la série en 200$a et le titre du volume en $i, là où la
    # BnF met le titre du volume en $a et la série en zone 461.
    meta = parse_record(load("sudoc_one_piece.xml"), "9782723489898", "18048074X")
    assert meta is not None
    assert meta.series == "One piece"
    assert meta.volume == 2
    assert meta.title == "Luffy versus la bande à Baggy"
    assert meta.authors == ["Eiichirô Oda"]
    assert meta.publisher == "Glénat"
    assert meta.published_date == "2013"
    assert meta.page_count == 192
    assert meta.language == "Français"
    assert meta.source_url == "https://www.sudoc.fr/18048074X"


def test_genre_plus_precis_que_bandes_dessinees():
    meta = parse_record(load("sudoc_one_piece.xml"), "9782723489898")
    assert meta is not None
    assert "Mangas" in meta.genres
    assert "Shônen" in meta.genres


def test_resume_de_quatrieme_de_couverture():
    meta = parse_record(load("sudoc_roman.xml"), "9782021563313", "279617860")
    assert meta is not None
    assert meta.title == "Le Mystère de la maison aux Trois Ormes"
    assert meta.authors == ["Valentin Musso"]
    assert meta.page_count == 364
    assert meta.synopsis and "commissaire Forestier" in meta.synopsis
    # Une notice sans série ne doit pas en inventer une.
    assert meta.series is None


def test_le_sudoc_ne_fournit_pas_de_couverture():
    meta = parse_record(load("sudoc_roman.xml"), "9782021563313")
    assert meta is not None
    assert meta.cover_url is None


@pytest.mark.parametrize("payload", ["", "pas du xml", "<record>"])
def test_reponse_illisible_ne_leve_pas(payload):
    assert parse_record(payload, "9782021563313") is None


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("<ppn>18048074X</ppn>", ["18048074X"]),
        ("<ppn>009689737</ppn><ppn>179407260</ppn>", ["009689737", "179407260"]),
        ("<error>Notice introuvable</error>", []),
        ("<ppn>12</ppn>", []),
    ],
)
def test_extraction_des_ppn(texte, attendu):
    assert PPN_RE.findall(texte) == attendu
