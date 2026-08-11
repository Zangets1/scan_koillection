"""Catalogue général de la BnF via le service SRU (format UNIMARC).

C'est la meilleure source pour l'édition francophone : elle fournit la série
(zone 461), le tome, le nombre de pages, le genre et — via les notices Electre —
un vrai résumé, ce que ni OpenLibrary ni Google Books ne donnent en français.

Documentation : https://api.bnf.fr/fr/api-sru-catalogue-general
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

import httpx

from ..models import BookMeta
from . import unimarc
from .base import Provider

SRU_URL = "https://catalogue.bnf.fr/api/SRU"
MXC = "{info:lc/xmlns/marcxchange-v2}"


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
    for element in root.iter(f"{MXC}record"):
        meta = unimarc.parse(unimarc.Record(element, MXC), isbn13, "bnf")
        if meta is None:
            continue
        ark = element.get("id") or ""
        if ark.startswith("ark:"):
            meta.source_url = f"https://catalogue.bnf.fr/{ark}"
            meta.cover_url = (
                f"https://catalogue.bnf.fr/couverture?&appName=NE&idArk={ark}&couverture=1"
            )
        candidates.append(meta)

    return unimarc.best_record(candidates, isbn13)
