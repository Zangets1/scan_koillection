"""Analyse des notices UNIMARC de la BnF (réponses réelles figées en fixtures)."""

from pathlib import Path

import pytest

from app.providers.bnf import parse_sru

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_notice_de_manga_donne_serie_tome_et_resume():
    meta = parse_sru(load("bnf_one_piece.xml"), "9782723489898")
    assert meta is not None
    assert meta.title == "Aux prises avec Baggy et ses hommes"
    assert meta.authors == ["Eiichiro Oda"]
    assert meta.publisher == "Glénat"
    assert meta.published_date == "2013"
    assert meta.page_count == 208
    # La zone 461 porte la série, pas la collection éditoriale « Shonen manga ».
    assert meta.series == "One piece"
    assert meta.volume == 2
    assert meta.genres[0] == "Bandes dessinées"
    assert meta.synopsis and "roi des pirates" in meta.synopsis
    assert meta.language == "Français"
    assert meta.cover_url and meta.cover_url.startswith("https://catalogue.bnf.fr/couverture")


def test_collection_editoriale_nest_pas_une_serie():
    # « 1984 » paraît dans la collection Folio n°822 : ce n'est pas une série et
    # cela ne doit pas déclencher la création d'une sous-collection « Folio ».
    meta = parse_sru(load("bnf_1984.xml"), "9782070368228")
    assert meta is not None
    assert meta.title == "1984"
    assert meta.series is None
    assert meta.volume is None
    assert meta.page_count == 438


def test_collection_de_poche_avec_numero_nest_pas_une_serie():
    # Cette notice porte « Folio junior n°1364 » mais aucune zone 461 : le
    # numéro de collection ne doit pas devenir un numéro de tome. La série
    # « Harry Potter » viendra d'OpenLibrary à la fusion.
    meta = parse_sru(load("bnf_harry_potter.xml"), "9782070643066")
    assert meta is not None
    assert meta.authors == ["J.K. Rowling"]
    assert meta.page_count == 1036
    assert meta.series is None
    assert meta.volume is None


def test_reponse_vide():
    assert parse_sru(load("bnf_vide.xml"), "9782070368228") is None


@pytest.mark.parametrize("payload", ["", "pas du xml", "<srw:incomplet>"])
def test_reponse_illisible_ne_leve_pas(payload):
    assert parse_sru(payload, "9782070368228") is None
