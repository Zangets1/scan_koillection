import pytest

from app import isbn


def test_normalise_les_formes_courantes():
    assert isbn.normalize("978-2-07-036822-8") == "9782070368228"
    assert isbn.normalize("ISBN 978 2 07 036822 8") == "9782070368228"
    assert isbn.normalize("207036822X") == "9782070368228"


def test_conversion_isbn10_isbn13():
    assert isbn.to_isbn13("207036822X") == "9782070368228"
    assert isbn.to_isbn10("9782070368228") == "207036822X"
    # Les ISBN-13 en 979 n'ont pas d'équivalent en 10 chiffres.
    assert isbn.to_isbn10("9791234567896") is None


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ("9782070368229", "Clé de contrôle"),
        ("2070368221", "Clé de contrôle"),
        ("9771234567003", "ISSN"),
        ("3560070123452", "978/979"),
        ("12345", "10 ou 13"),
        ("", "Aucun code"),
    ],
)
def test_rejette_les_codes_invalides(value, fragment):
    with pytest.raises(isbn.InvalidISBN) as error:
        isbn.normalize(value)
    assert fragment in str(error.value)


def test_detecte_les_ean_de_livre():
    assert isbn.is_book_ean("9782070368228")
    assert not isbn.is_book_ean("3560070123452")


def test_affichage_avec_tirets():
    assert isbn.hyphenate("9782070368228") == "978-2-0703-6822-8"
