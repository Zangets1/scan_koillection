"""K10plus — catalogue collectif des bibliothèques allemandes, en MARC21.

Retenu pour les éditions anglaises et américaines, que la BnF ignore et
qu'OpenLibrary décrit sans pagination ni série. Mesuré sur 55 ISBN anglophones :
il en connaît 35 %, toujours avec l'éditeur, presque toujours avec la pagination,
et il donne le pays d'édition réel — la seule source de cette information,
l'ISBN ne la portant pas.

Il ne fait découvrir aucun livre qu'OpenLibrary ignore : c'est un complément de
champs, pas un complément de couverture, exactement comme le SUDOC vis-à-vis de
la BnF.

**Volontairement limité à l'aire anglophone.** Sur les ISBN 978-2, mesure faite,
il ne comble aucun champ que la BnF et le SUDOC n'aient déjà, mais il coûte une
connexion de plus et une chance supplémentaire de heurter ``LOOKUP_DEADLINE`` :
l'y autoriser ajoutait 205 ms à la médiane française et faisait passer le
neuvième décile de 1,2 s à 4,0 s.

Ses zones de résumé et de genre sont écartées. Elles sont tantôt en allemand
(« Kinderbuch », « Jugendbuch » pour l'édition anglaise de Harry Potter), tantôt
en anglais selon la bibliothèque qui a rédigé la notice, et rien dans le format
ne permet de le savoir à l'avance : la zone 041 déclare la langue du *livre*,
pas celle du résumé. Faute de pouvoir trier, on ne garde que le factuel — ce qui
ne coûte rien, la mesure n'attribuant à ce catalogue aucun apport hors des
champs structurels (série, pagination, langue, pays).

Documentation : https://wiki.k10plus.de/display/K10PLUS/SRU
"""

from __future__ import annotations

import httpx

from ..models import BookMeta
from . import marc21
from .base import Provider

SRU_URL = "https://sru.k10plus.de/opac-de-627"
OPAC_URL = "https://opac.k10plus.de/DB=2.299/CMD?ACT=SRCHA&IKT=1007&TRM="


class K10plusProvider(Provider):
    name = "k10plus"
    label = "K10plus"
    groups = frozenset({"en"})

    async def fetch(self, client: httpx.AsyncClient, isbn13: str) -> BookMeta | None:
        response = await client.get(
            SRU_URL,
            params={
                "version": "1.1",
                "operation": "searchRetrieve",
                # `pica.isb` est l'index ISBN : il accepte la forme à treize
                # chiffres sans tirets, telle que le scanner la produit.
                "query": f"pica.isb={isbn13}",
                "maximumRecords": "3",
                "recordSchema": "marcxml",
            },
        )
        response.raise_for_status()

        meta = marc21.parse_sru(response.text, isbn13, self.name)
        if meta is None:
            return None

        # Résumé et vedettes sont dans la langue du catalogueur, allemande ou
        # anglaise selon la notice, sans moyen de le déterminer : on ne garde
        # que ce qui ne dépend pas de la langue.
        meta.synopsis = None
        meta.genres = []
        meta.subjects = []
        meta.source_url = f"{OPAC_URL}{isbn13}"
        return meta
