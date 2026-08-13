"""Lecture d'une notice MARC21, pendant de :mod:`app.providers.unimarc`.

Le monde francophone catalogue en UNIMARC, le monde anglo-saxon en MARC21. Les
deux décrivent les mêmes livres, mais les zones ne portent pas les mêmes
numéros : le titre est en 245 et non en 200, l'éditeur en 264 ou 260 et non en
214 ou 210, la pagination en 300 et non en 215. D'où ce module séparé plutôt
qu'un aiguillage dans le précédent.

Deux particularités du format méritent d'être signalées :

* les noms y sont indexés à l'envers (« Rowling, J. K. »), il faut les remettre
  à l'endroit avant de les afficher ;
* la zone de contrôle 008 porte, aux positions 15 à 17, le **pays d'édition**.
  C'est la seule source de cette information : l'ISBN ne la contient pas, son
  groupe « 978-0 / 978-1 » couvrant indistinctement le Royaume-Uni, les
  États-Unis, l'Australie et l'Irlande.

Documentation : https://www.loc.gov/marc/bibliographic/
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from ..isbn import clean as clean_isbn
from ..isbn import is_valid_isbn10, is_valid_isbn13, to_isbn13
from ..models import BookMeta
from ..series import parse_volume
from .base import clean_text, dedupe

MARC = "{http://www.loc.gov/MARC21/slim}"

#: Langues MARC (ISO 639-2) → étiquette lisible. Même table qu'en UNIMARC.
LANGUAGES = {
    "fre": "Français", "fra": "Français", "eng": "Anglais", "jpn": "Japonais",
    "spa": "Espagnol", "ger": "Allemand", "deu": "Allemand", "ita": "Italien",
    "por": "Portugais", "rus": "Russe", "chi": "Chinois", "zho": "Chinois",
    "kor": "Coréen", "dut": "Néerlandais", "nld": "Néerlandais", "lat": "Latin",
}

#: Codes pays MARC (zone 008/15-17) → pays d'édition lisible. La liste complète
#: en compte plusieurs centaines ; seuls les pays d'édition courants pour une
#: bibliothèque francophone sont traduits, le reste étant ignoré.
COUNTRIES = {
    "xxu": "États-Unis", "nyu": "États-Unis", "cau": "États-Unis",
    "mau": "États-Unis", "ilu": "États-Unis", "pau": "États-Unis",
    "mnu": "États-Unis", "txu": "États-Unis", "nju": "États-Unis",
    "enk": "Royaume-Uni", "xxk": "Royaume-Uni", "stk": "Royaume-Uni",
    "wlk": "Royaume-Uni", "nik": "Royaume-Uni",
    "fr": "France", "ja": "Japon", "gw": "Allemagne", "it": "Italie",
    "sp": "Espagne", "be": "Belgique", "sz": "Suisse",
    "quc": "Canada", "onc": "Canada", "bcc": "Canada",
    "at": "Australie", "nz": "Nouvelle-Zélande", "ie": "Irlande",
}

#: Codes ISO 3166 rencontrés en zone 044, parfois préfixés « XA- » ou « XD- ».
_ISO_COUNTRIES = {
    "GB": "Royaume-Uni", "US": "États-Unis", "FR": "France", "JP": "Japon",
    "DE": "Allemagne", "CA": "Canada", "IT": "Italie", "ES": "Espagne",
    "BE": "Belgique", "CH": "Suisse", "AU": "Australie", "IE": "Irlande",
}


class Record:
    """Accès aux zones et sous-zones d'une notice, avec ou sans espace de noms."""

    def __init__(self, element: ET.Element, namespace: str = MARC) -> None:
        self.element = element
        self.ns = namespace

    def control(self, tag: str) -> str:
        for field in self.element.findall(f"{self.ns}controlfield"):
            if field.get("tag") == tag:
                return field.text or ""
        return ""

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
    """Convertit une notice MARC21 en :class:`BookMeta`, ou ``None`` si inexploitable."""
    meta = BookMeta(sources=[source])

    _read_identifiers(record, meta, wanted_isbn)
    if not _read_title(record, meta):
        return None
    _read_authors(record, meta)
    _read_publication(record, meta)
    _read_extent(record, meta)
    _read_series(record, meta)
    _read_subjects(record, meta)
    _read_summary(record, meta)
    _read_language(record, meta)
    meta.country = _read_country(record)
    return meta


def _read_identifiers(record: Record, meta: BookMeta, wanted_isbn: str) -> None:
    # Une notice porte souvent plusieurs 020 (broché, relié, numérique). On
    # retient en priorité celui qui correspond à l'ISBN demandé.
    for field in record.fields("020"):
        raw = record.first(field, "a")
        if not raw:
            continue
        # « 0747532745 (pbk.) » : le qualificatif suit le numéro.
        value = clean_isbn(raw.split()[0])
        if not (is_valid_isbn13(value) or is_valid_isbn10(value)):
            continue
        candidate = to_isbn13(value)
        if candidate == wanted_isbn or not meta.isbn13:
            meta.isbn13 = candidate
            meta.isbn10 = value if is_valid_isbn10(value) else None
        if candidate == wanted_isbn:
            break
    if not meta.isbn13:
        meta.isbn13 = wanted_isbn


def _read_title(record: Record, meta: BookMeta) -> bool:
    for field in record.fields("245"):
        title = clean_text(record.first(field, "a"))
        if not title:
            continue
        meta.title = title
        meta.subtitle = clean_text(record.first(field, "b"))
        # $n « Book 3 » et $p « The prisoner of Azkaban » : numéro et titre de
        # partie. Leur présence signale une série, comme le $i du SUDOC.
        part_name = clean_text(record.first(field, "p"))
        if part_name:
            meta.series = title
            meta.title = part_name
            meta.volume = parse_volume(record.first(field, "n"))
        return True
    return False


def _read_authors(record: Record, meta: BookMeta) -> None:
    names: list[str] = []
    for tag in ("100", "110", "700"):
        for field in record.fields(tag):
            # $e « translator », « illustrator »… : en 700, seuls les auteurs
            # comptent. La zone 100 est la vedette principale, jamais un rôle
            # secondaire.
            role = (record.first(field, "e") or record.first(field, "4") or "").lower()
            if tag == "700" and role and not re.search(r"aut|creat|writ", role):
                continue
            name = _flip(record.first(field, "a"))
            if name:
                names.append(name)
    meta.authors = dedupe(names)[:5]


def _flip(name: str | None) -> str:
    """« Rowling, J. K., 1965- » → « J. K. Rowling ».

    MARC indexe au nom de famille et accole volontiers les dates de vie.

    La ponctuation se nettoie ici plutôt que par :func:`clean_text`, qui retire
    tous les points finaux : « J. K. » y perdrait le sien et ressortirait en
    « J. K Rowling ».
    """
    text = " ".join((name or "").split())
    text = re.sub(r"\s*\(.*?\)\s*", " ", text)
    # Dates de vie en fin de vedette : « Tolkien, J. R. R., 1892-1973 ».
    text = re.sub(r",?\s*\d{4}\s*-\s*\d{0,4}\s*$", "", text)
    text = text.strip().rstrip(",;/ ")
    if "," in text:
        surname, _, given = text.partition(",")
        text = f"{given.strip()} {surname.strip()}".strip()
    return " ".join(text.split())


def _read_publication(record: Record, meta: BookMeta) -> None:
    # 264 (RDA) prime sur 260 (AACR2), les deux coexistant selon l'âge de la notice.
    for tag in ("264", "260"):
        for field in record.fields(tag):
            # En 264, l'indicateur 2 distingue publication (1) de production (0),
            # distribution (2) et fabrication (3). Seule la publication nous intéresse.
            if tag == "264" and field.get("ind2") not in (None, "", "1"):
                continue
            if not meta.publisher:
                meta.publisher = clean_text(record.first(field, "b"))
            if not meta.published_date:
                meta.published_date = extract_year(record.first(field, "c"))
        if meta.publisher and meta.published_date:
            return
    if not meta.published_date:
        # Repli sur la date de la zone de contrôle 008 (positions 7 à 10).
        meta.published_date = extract_year(record.control("008")[7:11])


def _read_extent(record: Record, meta: BookMeta) -> None:
    for field in record.fields("300"):
        pages = extract_pages(record.first(field, "a"))
        if pages:
            meta.page_count = pages
            return


def _read_series(record: Record, meta: BookMeta) -> None:
    """Distingue la vraie série de la collection éditoriale, comme en UNIMARC.

    « Penguin classics » est une collection et ne doit pas créer de
    sous-collection dans Koillection ; « Discworld ; 12 » est une série. Le
    numéro de volume fait la différence : une collection sans numérotation
    n'en est pas une au sens du rangement.
    """
    if meta.series:
        return
    # 830 = vedette de collection normalisée, 490 = mention transcrite du livre.
    for tag in ("830", "490"):
        for field in record.fields(tag):
            title = clean_text(record.first(field, "a"))
            volume = parse_volume(record.first(field, "v"))
            if not title or volume is None:
                continue
            meta.series = clean_text(re.sub(r"\s*;\s*$", "", title))
            meta.volume = volume
            return


def _read_subjects(record: Record, meta: BookMeta) -> None:
    # 655 porte le genre ou la forme (« Fantasy fiction », « Comic books ») :
    # c'est l'équivalent de la zone 608 de l'UNIMARC. La 650 indexe le sujet,
    # nettement plus bruité, et sert de repli comme la 606.
    genres = [
        clean_text(value) or ""
        for field in record.fields("655")
        for value in record.subfields(field, "a")
    ]
    meta.genres = dedupe([g for g in genres if g])[:6]

    subjects = [
        clean_text(value) or ""
        for field in record.fields("650")
        for value in record.subfields(field, "a")
    ]
    meta.subjects = dedupe([s for s in subjects if s])[:6]


def _read_summary(record: Record, meta: BookMeta) -> None:
    for field in record.fields("520"):
        synopsis = clean_text(record.first(field, "a"))
        if synopsis:
            meta.synopsis = synopsis
            return


def _read_language(record: Record, meta: BookMeta) -> None:
    for field in record.fields("041"):
        code = record.first(field, "a")
        if code:
            meta.language = LANGUAGES.get(code.lower(), code)
            return
    code = record.control("008")[35:38].strip()
    if code:
        meta.language = LANGUAGES.get(code.lower(), code)


def _read_country(record: Record) -> str | None:
    """Pays d'édition, lu dans la notice — jamais déduit de l'ISBN.

    Le code-barres ne le porte pas : « 978-0 » et « 978-1 » désignent l'aire
    anglophone dans son ensemble. Seul le catalogue sait si le livre a été
    publié à Londres ou à New York, et il ne le dit pas toujours.
    """
    code = record.control("008")[15:18].strip().lower()
    if code in COUNTRIES:
        return COUNTRIES[code]
    for field in record.fields("044"):
        for raw in record.subfields(field, "c") + record.subfields(field, "a"):
            # Le catalogage allemand préfixe le code ISO d'une zone : « XA-GB ».
            iso = raw.split("-")[-1].strip().upper()
            if iso in _ISO_COUNTRIES:
                return _ISO_COUNTRIES[iso]
    return None


def extract_year(raw: str | None) -> str | None:
    match = re.search(r"(1[0-9]{3}|20[0-9]{2})", raw or "")
    return match.group(1) if match else None


def extract_pages(extent: str | None) -> int | None:
    """« xii, 223 p. » → 223, « 223 pages » → 223, « 223 S. » → 223."""
    if not extent:
        return None
    matches = re.findall(r"(\d{1,5})\s*(?:p\b|pages?|S\b|Seiten)", extent, flags=re.IGNORECASE)
    if not matches:
        return None
    # « xii, 345 p. » cumule parfois plusieurs séquences : on garde la plus grande.
    pages = max(int(m) for m in matches)
    return pages if 0 < pages < 20000 else None


def best_record(candidates: list[BookMeta], isbn13: str) -> BookMeta | None:
    """Retient la notice correspondant à l'ISBN demandé, puis la plus complète."""
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


def parse_sru(xml_text: str, isbn13: str, source: str, namespace: str = MARC) -> BookMeta | None:
    """Analyse une réponse SRU contenant des notices MARC21."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    candidates: list[BookMeta] = []
    for element in root.iter(f"{namespace}record"):
        meta = parse(Record(element, namespace), isbn13, source)
        if meta is not None:
            candidates.append(meta)
    return best_record(candidates, isbn13)
