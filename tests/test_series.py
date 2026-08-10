import pytest

from app import series


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("One Piece, Tome 12 : Et ainsi commence la légende",
         ("One Piece", 12, "Et ainsi commence la légende")),
        ("Harry Potter - Vol. 3 - Le prisonnier d'Azkaban",
         ("Harry Potter", 3, "Le prisonnier d'Azkaban")),
        ("Les Misérables, T2", ("Les Misérables", 2, "Les Misérables, T2")),
        ("Berserk 14", ("Berserk", 14, "Berserk 14")),
        ("Le Seigneur des anneaux, tome III", ("Le Seigneur des anneaux", 3, "Le Seigneur des anneaux, tome III")),
    ],
)
def test_extraction_serie_et_tome(title, expected):
    found_series, volume, _ = series.split_series(title)
    assert (found_series, volume) == (expected[0], expected[1])


@pytest.mark.parametrize("title", ["1984", "Fahrenheit 451", "Dune", ""])
def test_pas_de_faux_positif(title):
    found_series, volume, remaining = series.split_series(title)
    assert found_series is None
    assert volume is None
    assert remaining == title


def test_parse_volume():
    assert series.parse_volume("t. 12") == 12
    assert series.parse_volume("XII") == 12
    assert series.parse_volume(7) == 7
    assert series.parse_volume("") is None
    assert series.parse_volume(None) is None


def test_enrich_complete_depuis_le_titre():
    title, found_series, volume = series.enrich("Naruto, Tome 4 : Le pont des héros", None, None)
    assert (title, found_series, volume) == ("Le pont des héros", "Naruto", 4)


def test_enrich_ne_recouvre_pas_une_serie_connue():
    # La zone UNIMARC 461 fait autorité sur l'heuristique du titre.
    title, found_series, volume = series.enrich("Aux prises avec Baggy", "One piece", 2)
    assert (title, found_series, volume) == ("Aux prises avec Baggy", "One piece", 2)
