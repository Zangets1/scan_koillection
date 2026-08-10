"""Normalisation et validation des ISBN (et des EAN-13 lus au scanner)."""

from __future__ import annotations

import re

_CLEAN_RE = re.compile(r"[^0-9Xx]")


class InvalidISBN(ValueError):
    """Levée quand une chaîne ne peut pas être interprétée comme un ISBN."""


def clean(raw: str) -> str:
    """Retire tirets, espaces et préfixes ``ISBN``."""
    return _CLEAN_RE.sub("", (raw or "").strip()).upper()


def is_valid_isbn10(value: str) -> bool:
    if len(value) != 10:
        return False
    total = 0
    for index, char in enumerate(value):
        if char == "X":
            if index != 9:
                return False
            digit = 10
        elif char.isdigit():
            digit = int(char)
        else:
            return False
        total += (10 - index) * digit
    return total % 11 == 0


def is_valid_isbn13(value: str) -> bool:
    if len(value) != 13 or not value.isdigit():
        return False
    total = sum(int(char) * (1 if index % 2 == 0 else 3) for index, char in enumerate(value))
    return total % 10 == 0


def to_isbn13(value: str) -> str:
    """Convertit un ISBN-10 en ISBN-13 ; renvoie l'ISBN-13 tel quel."""
    value = clean(value)
    if is_valid_isbn13(value):
        return value
    if is_valid_isbn10(value):
        core = "978" + value[:9]
        total = sum(int(char) * (1 if index % 2 == 0 else 3) for index, char in enumerate(core))
        return core + str((10 - total % 10) % 10)
    raise InvalidISBN(f"ISBN invalide : {value or '(vide)'}")


def to_isbn10(value: str) -> str | None:
    """Convertit un ISBN-13 ``978`` en ISBN-10 (utile pour OpenLibrary/Amazon)."""
    value = clean(value)
    if is_valid_isbn10(value):
        return value
    if not is_valid_isbn13(value) or not value.startswith("978"):
        return None
    core = value[3:12]
    total = sum((10 - index) * int(char) for index, char in enumerate(core))
    check = (11 - total % 11) % 11
    return core + ("X" if check == 10 else str(check))


def is_book_ean(value: str) -> bool:
    """Vrai si l'EAN-13 appartient au domaine du livre (Bookland 978/979)."""
    value = clean(value)
    return is_valid_isbn13(value) and value[:3] in {"978", "979"}


def normalize(raw: str) -> str:
    """Point d'entrée unique : renvoie un ISBN-13 valide ou lève :class:`InvalidISBN`.

    Les codes EAN-13 hors Bookland (produits de grande distribution, ISSN 977…)
    sont rejetés : c'est ce qui permet au scanner de refuser un code-barres
    qui n'est pas celui d'un livre.
    """
    value = clean(raw)
    if not value:
        raise InvalidISBN("Aucun code saisi.")
    if len(value) == 13:
        if not is_valid_isbn13(value):
            raise InvalidISBN("Clé de contrôle EAN-13 incorrecte, code mal lu.")
        if value[:3] == "977":
            raise InvalidISBN("Ce code est un ISSN (revue), pas un ISBN de livre.")
        if value[:3] not in {"978", "979"}:
            raise InvalidISBN("Ce code-barres n'est pas un ISBN (préfixe 978/979 attendu).")
        return value
    if len(value) == 10:
        if not is_valid_isbn10(value):
            raise InvalidISBN("Clé de contrôle ISBN-10 incorrecte, code mal lu.")
        return to_isbn13(value)
    raise InvalidISBN(f"Longueur inattendue ({len(value)} caractères) : un ISBN fait 10 ou 13 chiffres.")


def hyphenate(isbn13: str) -> str:
    """Découpage lisible et volontairement approximatif (affichage seulement)."""
    value = clean(isbn13)
    if len(value) != 13:
        return value
    return f"{value[:3]}-{value[3:4]}-{value[4:8]}-{value[8:12]}-{value[12:]}"
