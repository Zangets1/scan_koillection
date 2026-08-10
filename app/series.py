"""Extraction série / tome à partir d'un titre.

Les catalogues francophones sont très irréguliers : la BnF met la série dans le
champ UNIMARC 461/225, mais OpenLibrary ou Google Books la noient dans le titre
(« One Piece, Tome 12 : Et ainsi commence la légende »). Ce module rattrape ces
cas et sert aussi de filet quand aucune source ne renseigne la série.
"""

from __future__ import annotations

import re

_ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
    "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
}

_VOLUME_WORDS = r"(?:tome|tomes|vol\.?|volume|livre|part(?:ie)?|book|band|n°|no\.)"

# « Série, Tome 3 : Titre » / « Série - Vol. 3 - Titre » / « Série T3 »
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"^(?P<series>.+?)\s*[,\-–—:]?\s*{_VOLUME_WORDS}\s*(?P<volume>\d{{1,3}})\b\s*[:\-–—,.]?\s*(?P<title>.*)$",
        re.IGNORECASE,
    ),
    # « Série, T3 : Titre » (abréviation collée)
    re.compile(
        r"^(?P<series>.+?)\s*[,\-–—:]\s*[Tt]\.?\s*(?P<volume>\d{1,3})\b\s*[:\-–—,.]?\s*(?P<title>.*)$"
    ),
    # « Série, tome III : Titre »
    re.compile(
        rf"^(?P<series>.+?)\s*[,\-–—:]?\s*{_VOLUME_WORDS}\s*(?P<volume>[IVX]{{1,6}})\b\s*[:\-–—,.]?\s*(?P<title>.*)$",
        re.IGNORECASE,
    ),
    # « Série 12 » ou « Série, 12 » en toute fin de titre (usage manga BnF/OpenLibrary).
    # Volontairement limité à deux chiffres pour ne pas casser « Fahrenheit 451 ».
    re.compile(r"^(?P<series>.+?)[\s,.]+(?P<volume>\d{1,2})\s*$"),
)


def parse_volume(raw: str | int | None) -> int | None:
    """Transforme ``"12"``, ``"t. 12"``, ``"XII"`` en entier."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if 0 < raw < 1000 else None
    text = str(raw).strip()
    if not text:
        return None
    digits = re.search(r"\d{1,3}", text)
    if digits:
        value = int(digits.group(0))
        return value if 0 < value < 1000 else None
    roman = _ROMAN.get(text.upper().strip(". "))
    return roman


def split_series(title: str) -> tuple[str | None, int | None, str]:
    """Renvoie ``(série, tome, titre_du_volume)`` déduits d'un titre complet.

    Le titre retourné est celui du volume seul lorsqu'il a pu être isolé, sinon
    le titre d'origine inchangé.
    """
    text = (title or "").strip()
    if not text:
        return None, None, text

    for pattern in _PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        series = match.group("series").strip(" ,.:;-–—")
        volume = parse_volume(match.group("volume"))
        volume_title = (match.groupdict().get("title") or "").strip(" ,.:;-–—")
        # Un « titre » d'un seul caractère ou une série vide = faux positif.
        if not series or len(series) < 2 or volume is None:
            continue
        # « 1984 » ne doit pas devenir la série « 198 » tome 4.
        if series.isdigit():
            continue
        return series, volume, volume_title or text
    return None, None, text


def enrich(
    title: str,
    series: str | None,
    volume: int | None,
) -> tuple[str, str | None, int | None]:
    """Complète série/tome à partir du titre si la source ne les fournit pas.

    Ne réécrit jamais une série déjà connue : les catalogues de bibliothèque
    (BnF) sont plus fiables que l'heuristique.
    """
    guessed_series, guessed_volume, volume_title = split_series(title)

    final_series = series or guessed_series
    final_volume = volume if volume is not None else guessed_volume

    # On ne raccourcit le titre que si la série retenue vient bien du titre.
    if guessed_series and final_series and _same(guessed_series, final_series):
        title = volume_title

    return title, final_series, final_volume


def _same(left: str, right: str) -> bool:
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.lower())  # noqa: E731
    return normalize(left) == normalize(right)
