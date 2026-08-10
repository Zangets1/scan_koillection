"""Catalogue général de la BnF via le service SRU (format UNIMARC).

C'est la meilleure source pour l'édition francophone : elle fournit la série
(zone 461), le tome, le nombre de pages, le genre et — via les notices Electre —
un vrai résumé, ce que ni OpenLibrary ni Google Books ne donnent en français.

Documentation : https://api.bnf.fr/fr/api-sru-catalogue-general
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import httpx

from ..models import BookMeta
from ..series import parse_volume
from .base import Provider, clean_text, dedupe

SRU_URL = "https://catalogue.bnf.fr/api/SRU"
MXC = "{info:lc/xmlns/marcxchange-v2}"

#: Codes de fonction UNIMARC retenus comme « auteur »
AUTHOR_ROLES = {"070", "0070", "aut"}
#: Langues ISO 639-2 → étiquette lisible
_LANGUAGES = {
    "fre": "Français", "fra": "Français", "eng": "Anglais", "jpn": "Japonais",
    "spa": "Espagnol", "ger": "Allemand", "deu": "Allemand", "ita": "Italien",
    "por": "Portugais", "rus": "Russe", "chi": "Chinois", "zho": "Chinois",
    "kor": "Coréen", "dut": "Néerlandais", "nld": "Néerlandais", "lat": "Latin",
}


class BnfProvider(Provider):
    name = "bnf"
    label = "BnF"

    async def fetch(self, client: httpx.AsyncClient, isbn13: str) -> BookMeta | None:
        params = {
            "version": "1.2",
            "operation": "searchRetrieve",
            # `fuzzyISBN` accepte indifféremment ISBN-10, ISBN-13 et EAN, avec ou
            # sans tirets ; `bib.isbn` exige la forme exacte de la notice.
            "query": f'bib.fuzzyISBN any "{isbn13}"',
            "recordSchema": "unimarcXchange",
            "maximumRecords": "5",
        }
        response = await client.get(SRU_URL, params=params)
        response.raise_for_status()
        return parse_sru(response.text, isbn13)


def parse_sru(xml_text: str, isbn13: str) -> BookMeta | None:
    """Analyse une réponse SRU et retourne la meilleure notice."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    candidates: list[BookMeta] = []
    for record in root.iter(f"{MXC}record"):
        meta = _parse_record(record, isbn13)
        if meta is not None:
            candidates.append(meta)

    if not candidates:
        return None

    # On privilégie la notice dont l'ISBN correspond exactement, puis la plus riche.
    def score(meta: BookMeta) -> tuple[int, int]:
        exact = 1 if meta.isbn13 == isbn13 else 0
        richness = sum(
            1
            for value in (meta.synopsis, meta.series, meta.page_count, meta.publisher, meta.genres)
            if value
        )
        return exact, richness

    return max(candidates, key=score)


def _subfields(field: ET.Element, code: str) -> list[str]:
    return [
        (sub.text or "").strip()
        for sub in field.findall(f"{MXC}subfield")
        if sub.get("code") == code and (sub.text or "").strip()
    ]


def _first(field: ET.Element, code: str) -> str | None:
    values = _subfields(field, code)
    return values[0] if values else None


def _fields(record: ET.Element, tag: str) -> list[ET.Element]:
    return [f for f in record.findall(f"{MXC}datafield") if f.get("tag") == tag]


def _parse_record(record: ET.Element, wanted_isbn: str) -> BookMeta | None:
    meta = BookMeta(sources=["bnf"])

    # --- identifiants -----------------------------------------------------
    from ..isbn import clean as clean_isbn
    from ..isbn import is_valid_isbn10, is_valid_isbn13, to_isbn13

    for field in _fields(record, "010"):
        raw = _first(field, "a")
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

    ark = record.get("id") or ""
    if ark.startswith("ark:"):
        meta.source_url = f"https://catalogue.bnf.fr/{ark}"
        meta.cover_url = (
            f"https://catalogue.bnf.fr/couverture?&appName=NE&idArk={ark}&couverture=1"
        )

    # --- titre et mention de responsabilité -------------------------------
    for field in _fields(record, "200"):
        title = clean_text(_first(field, "a"))
        if not title:
            continue
        meta.title = title
        meta.subtitle = clean_text(_first(field, "e"))
        statement = _first(field, "f")
        if statement:
            meta.authors = _split_authors(statement)
        break
    if not meta.title:
        return None

    # --- auteurs à partir des zones d'accès (plus fiables si 200$f absent) --
    if not meta.authors:
        names: list[str] = []
        for tag in ("700", "701", "702"):
            for field in _fields(record, tag):
                role = _first(field, "4")
                if tag == "702" and role not in AUTHOR_ROLES:
                    continue  # 702 = contributeur secondaire (traducteur, préfacier…)
                surname = clean_text(_first(field, "a"))
                given = clean_text(_first(field, "b"))
                if surname:
                    names.append(f"{given} {surname}".strip() if given else surname)
        meta.authors = dedupe(names)

    # --- éditeur et date (210 en ISBD, 214 en RDA-fr) ----------------------
    for tag in ("214", "210"):
        for field in _fields(record, tag):
            publisher = clean_text(_first(field, "c"))
            date = _first(field, "d")
            if publisher and not meta.publisher:
                meta.publisher = publisher
            if date and not meta.published_date:
                meta.published_date = _extract_year(date)
        if meta.publisher and meta.published_date:
            break

    # --- pagination --------------------------------------------------------
    for field in _fields(record, "215"):
        extent = _first(field, "a")
        pages = _extract_pages(extent)
        if pages:
            meta.page_count = pages
            break

    # --- série et tome -----------------------------------------------------
    meta.series, meta.volume = _extract_series(record)

    # --- genre et sujets ---------------------------------------------------
    genres: list[str] = []
    for field in _fields(record, "608"):  # forme, genre
        genres.extend(clean_text(v) or "" for v in _subfields(field, "a"))
    for field in _fields(record, "606"):  # sujets
        genres.extend(clean_text(v) or "" for v in _subfields(field, "a"))
    meta.genres = dedupe([g for g in genres if g])[:6]

    # --- résumé ------------------------------------------------------------
    for field in _fields(record, "330"):
        synopsis = clean_text(_first(field, "a"))
        if synopsis:
            meta.synopsis = synopsis
            break

    # --- langue ------------------------------------------------------------
    for field in _fields(record, "101"):
        code = _first(field, "a")
        if code:
            meta.language = _LANGUAGES.get(code.lower(), code)
            break

    return meta


def _extract_series(record: ET.Element) -> tuple[str | None, int | None]:
    """Distingue la vraie série (461) de la collection éditoriale (410).

    « 1984 » chez Gallimard porte la collection « Folio n°822 » : ce n'est pas
    une série et cela ne doit surtout pas créer une sous-collection « Folio ».
    « One Piece » porte en revanche une zone 461 « One piece » tome 2.
    """
    # 461 = ensemble auquel appartient la notice : c'est la série.
    for field in _fields(record, "461"):
        title = clean_text(_first(field, "t"))
        if title:
            return title, parse_volume(_first(field, "v"))

    # Sinon 225 (collection imprimée sur le livre), en écartant celles qui
    # correspondent à une collection d'éditeur déclarée en 410.
    publisher_collections = [
        (clean_text(_first(f, "t")) or "").casefold() for f in _fields(record, "410")
    ]
    for field in _fields(record, "225"):
        title = clean_text(_first(field, "a"))
        volume = parse_volume(_first(field, "v"))
        if not title or volume is None:
            continue
        key = title.casefold()
        if any(key in collection for collection in publisher_collections if collection):
            continue
        return title, volume

    return None, None


def _split_authors(statement: str) -> list[str]:
    """Découpe une mention de responsabilité « A, B et C »."""
    text = re.sub(
        r"\b(?:texte|scénario|dessins?|illustrations?|traduit|trad\.|adapt\.)[^;]*",
        "",
        statement,
        flags=re.IGNORECASE,
    )
    parts = re.split(r"\s*;\s*|\s*,\s*|\s+et\s+|\s*&\s*", text)
    return dedupe([clean_text(p) or "" for p in parts if clean_text(p)])[:5]


def _extract_year(raw: str) -> str | None:
    match = re.search(r"(1[0-9]{3}|20[0-9]{2})", raw or "")
    return match.group(1) if match else None


def _extract_pages(extent: str | None) -> int | None:
    """« 1 vol. (208 p.) » → 208, « 438 p. » → 438."""
    if not extent:
        return None
    matches = re.findall(r"(\d{1,5})\s*(?:p\b|pages?)", extent, flags=re.IGNORECASE)
    if not matches:
        return None
    # Certaines notices cumulent « XII-345 p. » : on garde le plus grand nombre.
    pages = max(int(m) for m in matches)
    return pages if 0 < pages < 20000 else None
