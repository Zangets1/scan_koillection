"""Lecture d'une notice UNIMARC, partagée par la BnF et le SUDOC.

Les deux catalogues renvoient le même format bibliographique : seul l'emballage
XML diffère (marcxchange avec un espace de noms côté BnF, UNIMARC nu côté
SUDOC). Tout ce qui suit — la distinction entre série et collection éditoriale,
l'extraction de la pagination, le choix des auteurs — leur est donc commun.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from ..isbn import clean as clean_isbn
from ..isbn import is_valid_isbn10, is_valid_isbn13, to_isbn13
from ..models import BookMeta
from ..series import parse_volume
from .base import clean_text, dedupe

#: Codes de fonction UNIMARC retenus comme « auteur »
AUTHOR_ROLES = {"070", "0070", "aut"}

#: Langues ISO 639-2 → étiquette lisible
LANGUAGES = {
    "fre": "Français", "fra": "Français", "eng": "Anglais", "jpn": "Japonais",
    "spa": "Espagnol", "ger": "Allemand", "deu": "Allemand", "ita": "Italien",
    "por": "Portugais", "rus": "Russe", "chi": "Chinois", "zho": "Chinois",
    "kor": "Coréen", "dut": "Néerlandais", "nld": "Néerlandais", "lat": "Latin",
}


class Record:
    """Accès aux zones et sous-zones d'une notice, quel que soit l'espace de noms."""

    def __init__(self, element: ET.Element, namespace: str = "") -> None:
        self.element = element
        self.ns = namespace

    def fields(self, tag: str) -> list[ET.Element]:
        return [
            field
            for field in self.element.findall(f"{self.ns}datafield")
            if field.get("tag") == tag
        ]

    def subfields(self, field: ET.Element, code: str) -> list[str]:
        return [
            (sub.text or "").strip()
            for sub in field.findall(f"{self.ns}subfield")
            if sub.get("code") == code and (sub.text or "").strip()
        ]

    def first(self, field: ET.Element, code: str) -> str | None:
        values = self.subfields(field, code)
        return values[0] if values else None


def parse(record: Record, wanted_isbn: str, source: str) -> BookMeta | None:
    """Convertit une notice UNIMARC en :class:`BookMeta`, ou ``None`` si inexploitable."""
    meta = BookMeta(sources=[source])

    _read_identifiers(record, meta, wanted_isbn)
    if not _read_title(record, meta):
        return None
    _read_authors(record, meta)
    _read_publication(record, meta)
    _read_extent(record, meta)

    if meta.series is None:
        meta.series, meta.volume = extract_series(record)

    _read_subjects(record, meta)
    _read_summary(record, meta)
    _read_language(record, meta)
    return meta


def _read_identifiers(record: Record, meta: BookMeta, wanted_isbn: str) -> None:
    for field in record.fields("010"):
        raw = record.first(field, "a")
        if not raw:
            continue
        value = clean_isbn(raw)
        if is_valid_isbn13(value) or is_valid_isbn10(value):
            meta.isbn13 = to_isbn13(value)
            if is_valid_isbn10(value):
                meta.isbn10 = value
            break
    if not meta.isbn13:
        meta.isbn13 = wanted_isbn


def _read_title(record: Record, meta: BookMeta) -> bool:
    for field in record.fields("200"):
        title = clean_text(record.first(field, "a"))
        if not title:
            continue

        # Le SUDOC place la série en $a et le titre du volume en $i, avec le
        # numéro de tome en $h (« Tome [2] » puis « 2 »). La BnF, elle, met
        # directement le titre du volume en $a et la série en zone 461.
        volume_title = clean_text(record.first(field, "i"))
        if volume_title:
            meta.series = title
            meta.volume = next(
                (
                    parsed
                    for parsed in (parse_volume(h) for h in record.subfields(field, "h"))
                    if parsed is not None
                ),
                None,
            )
            meta.title = volume_title
        else:
            meta.title = title

        meta.subtitle = clean_text(record.first(field, "e"))
        statement = record.first(field, "f")
        if statement:
            meta.authors = split_authors(statement)
        return True
    return False


def _read_authors(record: Record, meta: BookMeta) -> None:
    if meta.authors:
        return
    names: list[str] = []
    for tag in ("700", "701", "702"):
        for field in record.fields(tag):
            role = record.first(field, "4")
            if tag == "702" and role not in AUTHOR_ROLES:
                continue  # 702 = contributeur secondaire (traducteur, préfacier…)
            surname = clean_text(record.first(field, "a"))
            given = clean_text(record.first(field, "b"))
            if surname:
                names.append(f"{given} {surname}".strip() if given else surname)
    meta.authors = dedupe(names)


def _read_publication(record: Record, meta: BookMeta) -> None:
    # 210 en ISBD, 214 depuis RDA-fr : les deux coexistent selon l'âge de la notice.
    for tag in ("214", "210"):
        for field in record.fields(tag):
            publisher = clean_text(record.first(field, "c"))
            date = record.first(field, "d")
            if publisher and not meta.publisher:
                meta.publisher = publisher
            if date and not meta.published_date:
                meta.published_date = extract_year(date)
        if meta.publisher and meta.published_date:
            return


def _read_extent(record: Record, meta: BookMeta) -> None:
    for field in record.fields("215"):
        pages = extract_pages(record.first(field, "a"))
        if pages:
            meta.page_count = pages
            return


def _read_subjects(record: Record, meta: BookMeta) -> None:
    # La zone 608 porte la forme de l'œuvre (« Mangas », « Romans policiers ») :
    # c'est ce que l'on veut voir dans Koillection. La 606 indexe le sujet, avec
    # des vedettes RAMEAU parfois déroutantes hors contexte documentaire.
    genres: list[str] = []
    for field in record.fields("608"):
        genres.extend(clean_text(v) or "" for v in record.subfields(field, "a"))
    meta.genres = dedupe([g for g in genres if g])[:6]

    subjects: list[str] = []
    for field in record.fields("606"):
        subjects.extend(clean_text(v) or "" for v in record.subfields(field, "a"))
    meta.subjects = dedupe([s for s in subjects if s])[:6]


def _read_summary(record: Record, meta: BookMeta) -> None:
    for field in record.fields("330"):
        synopsis = clean_text(record.first(field, "a"))
        if synopsis:
            meta.synopsis = synopsis
            return


def _read_language(record: Record, meta: BookMeta) -> None:
    for field in record.fields("101"):
        code = record.first(field, "a")
        if code:
            meta.language = LANGUAGES.get(code.lower(), code)
            return


def extract_series(record: Record) -> tuple[str | None, int | None]:
    """Distingue la vraie série (461) de la collection éditoriale (410).

    « 1984 » chez Gallimard porte la collection « Folio n°822 » : ce n'est pas
    une série et cela ne doit surtout pas créer une sous-collection « Folio ».
    « One Piece » porte en revanche une zone 461 « One piece » tome 2.
    """
    for field in record.fields("461"):
        title = clean_text(record.first(field, "t"))
        if title:
            return title, parse_volume(record.first(field, "v"))

    # Sinon 225 (collection imprimée sur le livre), en écartant celles qui
    # correspondent à une collection d'éditeur déclarée en 410.
    publisher_collections = [
        (clean_text(record.first(f, "t")) or "").casefold() for f in record.fields("410")
    ]
    for field in record.fields("225"):
        title = clean_text(record.first(field, "a"))
        volume = parse_volume(record.first(field, "v"))
        if not title or volume is None:
            continue
        key = title.casefold()
        if any(key in collection for collection in publisher_collections if collection):
            continue
        return title, volume

    return None, None


def split_authors(statement: str) -> list[str]:
    """Découpe une mention de responsabilité « A, B et C »."""
    text = re.sub(
        r"\b(?:texte|scénario|dessins?|illustrations?|traduit|trad\.|adapt\.)[^;]*",
        "",
        statement,
        flags=re.IGNORECASE,
    )
    parts = re.split(r"\s*;\s*|\s*,\s*|\s+et\s+|\s*&\s*", text)
    return dedupe([clean_text(p) or "" for p in parts if clean_text(p)])[:5]


def extract_year(raw: str) -> str | None:
    match = re.search(r"(1[0-9]{3}|20[0-9]{2})", raw or "")
    return match.group(1) if match else None


def extract_pages(extent: str | None) -> int | None:
    """« 1 vol. (208 p.) » → 208, « 1 volume (192 pages) » → 192."""
    if not extent:
        return None
    matches = re.findall(r"(\d{1,5})\s*(?:p\b|pages?)", extent, flags=re.IGNORECASE)
    if not matches:
        return None
    # Certaines notices cumulent « XII-345 p. » : on garde le plus grand nombre.
    pages = max(int(m) for m in matches)
    return pages if 0 < pages < 20000 else None


def best_record(candidates: list[BookMeta], isbn13: str) -> BookMeta | None:
    """Retient la notice qui correspond à l'ISBN demandé, puis la plus complète."""
    if not candidates:
        return None

    def score(meta: BookMeta) -> tuple[int, int]:
        exact = 1 if meta.isbn13 == isbn13 else 0
        richness = sum(
            1
            for value in (meta.synopsis, meta.series, meta.page_count, meta.publisher, meta.genres)
            if value
        )
        return exact, richness

    return max(candidates, key=score)
