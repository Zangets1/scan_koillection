"""Library of Congress — dépôt légal des États-Unis, en MARC21.

**Absente de la liste par défaut**, à ajouter sciemment : elle n'expose son
service SRU que sur ``http://lx2.loc.gov:210`` — en clair, sur un port non
standard que beaucoup de réseaux domestiques, de FAI et de configurations
Docker filtrent. Là où le port est bloqué, la connexion n'échoue pas vite : elle
reste pendante jusqu'au plafond, et chaque scan anglophone attendrait alors
``LOOKUP_DEADLINE`` avant d'afficher la fiche. C'est la raison pour laquelle ce
fournisseur ne s'active qu'à la demande, une fois le port vérifié :

    python3 tools/mesure-loc.py

Mesuré depuis un réseau où le port passe, sur les 55 ISBN anglophones du banc
d'essai : elle en connaît 10 (18 %), en 388 ms de médiane — plus rapide
qu'OpenLibrary, donc sans effet sur le temps de réponse puisque les catalogues
sont interrogés en parallèle. Les notices trouvées sont presque toutes des
éditeurs américains (Scholastic, Ballantine, Tor, Andrews McMeel), ce qui est
attendu d'un dépôt légal national : sur une collection majoritairement
américaine, sa couverture serait meilleure que ces 18 %.

Son apport propre, une fois retiré ce qu'OpenLibrary et K10plus donnaient déjà :
la pagination sur 2 livres, et le **pays d'édition sur 8**, ce qui porte la
couverture de ce champ de 21 % à 36 %. Aucun livre qu'elle serait seule à
connaître. C'est étroit, et c'est le pays qui la justifie — la seule information
que l'ISBN ne porte pas.

Comme pour K10plus, ses zones de résumé et de vedettes matière sont écartées :
les vedettes LCSH sont un vocabulaire d'indexation anglophone (« Magic --
Juvenile fiction ») qui n'a pas sa place dans le champ Genre d'une fiche
française. Seul le factuel est retenu.

Documentation : https://www.loc.gov/standards/sru/resources/lcServers.html
"""

from __future__ import annotations

import httpx

from ..models import BookMeta
from . import marc21
from .base import Provider

SRU_URL = "http://lx2.loc.gov:210/LCDB"
CATALOGUE_URL = "https://catalog.loc.gov/vwebv/search?searchArg="


class LocProvider(Provider):
    name = "loc"
    label = "Library of Congress"
    groups = frozenset({"en"})

    async def fetch(self, client: httpx.AsyncClient, isbn13: str) -> BookMeta | None:
        response = await client.get(
            SRU_URL,
            params={
                "version": "1.1",
                "operation": "searchRetrieve",
                # `bath.isbn` est l'index ISBN du profil Bath, celui que la LC
                # documente. Mesure faite, il répond aussi bien à la forme à
                # treize chiffres qu'à l'ISBN-10 : inutile de tenter les deux,
                # ce qui doublerait le temps de réponse sur les quatre livres
                # sur cinq qu'elle ne possède pas.
                "query": f"bath.isbn={isbn13}",
                "maximumRecords": "3",
                "recordSchema": "marcxml",
            },
        )
        response.raise_for_status()

        meta = marc21.parse_sru(response.text, isbn13, self.name)
        if meta is None:
            return None

        # Vedettes LCSH et résumé : anglophones et destinés à l'indexation
        # documentaire. On ne garde que ce qui ne dépend pas de la langue.
        meta.synopsis = None
        meta.genres = []
        meta.subjects = []
        meta.source_url = f"{CATALOGUE_URL}{isbn13}"
        return meta
