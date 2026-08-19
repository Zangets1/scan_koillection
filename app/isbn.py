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


#: Groupes d'enregistrement ISBN, d'après le fichier officiel ``RangeMessage.xml``
#: de l'Agence internationale de l'ISBN (287 groupes, dont voici les seuls qui
#: intéressent ce projet).
#:
#: Un groupe désigne l'agence qui a enregistré l'éditeur : c'est une **aire
#: linguistique**, pas un pays. « 978-0 » et « 978-1 » forment un unique groupe
#: « English language » partagé par le Royaume-Uni, les États-Unis, l'Australie,
#: l'Irlande et le Canada anglophone. Aucun code-barres ne permet donc de
#: distinguer une édition anglaise d'une édition américaine — seules la notice
#: du catalogue et son code pays MARC le disent. Seuls 979-10 (France) et 979-8
#: (États-Unis) sont des groupes nationaux.
#:
#: L'ordre compte : les préfixes longs doivent être testés avant les courts,
#: « 979-10 » avant « 979-1 » n'existant pas mais « 978-84 » devant primer sur
#: un éventuel « 978-8 ».
_GROUPS: tuple[tuple[str, str], ...] = (
    ("97910", "fr"),   # France
    ("97911", "ko"),   # Corée du Sud
    ("97912", "it"),   # Italie
    ("9798", "en"),    # États-Unis, essentiellement de l'auto-édition
    ("97884", "es"),   # Espagne
    ("97888", "it"),   # Italie
    ("9780", "en"),    # aire anglophone
    ("9781", "en"),    # aire anglophone
    ("9782", "fr"),    # aire francophone
    ("9783", "de"),    # aire germanophone
    ("9784", "ja"),    # Japon
    ("9785", "ru"),    # aire russophone
    ("9787", "zh"),    # Chine
)


def registration_group(value: str) -> str:
    """Aire linguistique de l'éditeur : ``fr``, ``en``, ``ja``… ou ``""``.

    Sert à n'interroger que les catalogues susceptibles de connaître le livre :
    la BnF ne référence qu'un ISBN anglophone sur cinquante, openBD ne contient
    que du japonais. C'est une lecture de cinq chiffres, sans appel réseau.

    Renvoie une chaîne vide pour un groupe non répertorié, ce qui vaut « je ne
    sais pas » : les fournisseurs sont alors tous interrogés, comme avant.
    """
    value = clean(value)
    for prefix, group in _GROUPS:
        if value.startswith(prefix):
            return group
    return ""


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

