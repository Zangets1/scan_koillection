"""SUDOC — catalogue collectif des bibliothèques universitaires françaises.

Complément direct de la BnF : sur un échantillon de livres français récents,
il apporte un résumé sur environ un cinquième des titres pour lesquels la BnF
n'en a aucun, et un genre plus précis (« Mangas », « Shônen » plutôt que
« Bandes dessinées »). Il ne trouve en revanche presque rien que la BnF ignore :
c'est un complément de champs, pas un complément de couverture.

Deux appels sont nécessaires — l'ISBN donne un PPN, le PPN donne la notice —
mais le service reste plus rapide et bien plus fiable que son point d'accès SRU,
qui ne répondait que pour trois quarts des ISBN testés.

Documentation : https://abes.fr/reseau-sudoc/documentation-technique/
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import httpx

from ..models import BookMeta
from . import unimarc
from .base import Provider

ISBN2PPN_URL = "https://www.sudoc.fr/services/isbn2ppn"
RECORD_URL = "https://www.sudoc.fr"

#: Un PPN fait 9 caractères : 8 chiffres et une clé de contrôle numérique ou X.
PPN_RE = re.compile(r"<ppn>\s*([0-9]{8}[0-9Xx])\s*</ppn>")


class SudocProvider(Provider):
    name = "sudoc"
    label = "SUDOC"

    async def fetch(self, client: httpx.AsyncClient, isbn13: str) -> BookMeta | None:
        response = await client.get(f"{ISBN2PPN_URL}/{isbn13}")
        if response.status_code != 200:
            return None
        ppns = PPN_RE.findall(response.text)
        if not ppns:
            return None

        # Plusieurs PPN signalent plusieurs éditions du même ISBN ; on s'en tient
        # aux deux premières pour ne pas transformer une recherche en rafale.
        candidates: list[BookMeta] = []
        for ppn in ppns[:2]:
            record = await client.get(f"{RECORD_URL}/{ppn}.xml")
            if record.status_code != 200:
                continue
            meta = parse_record(record.text, isbn13, ppn)
            if meta is not None:
                candidates.append(meta)
        return unimarc.best_record(candidates, isbn13)


def parse_record(xml_text: str, isbn13: str, ppn: str = "") -> BookMeta | None:
    """Analyse une notice UNIMARC du SUDOC (XML sans espace de noms)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    meta = unimarc.parse(unimarc.Record(root), isbn13, "sudoc")
    if meta is None:
        return None
    if ppn:
        meta.source_url = f"https://www.sudoc.fr/{ppn}"
    # Le SUDOC n'expose pas de service de couverture : celle-ci viendra d'une
    # autre source lors de la fusion.
    return meta
