"""Détection des doublons : le même livre ne doit entrer qu'une fois.

Ces tests rejouent la panne du soir d'import — un scan qui « plante à moitié »
et laisse passer quatre fois le même livre. Trois défauts se cumulaient :

* un item du même nom mais **sans** ISBN n'était pas reconnu comme doublon,
  alors que c'est justement la trace d'un ajout précédent qui a mal fini ;
* deux validations simultanées cherchaient chacune un doublon avant que
  l'autre n'ait créé le sien, et passaient toutes les deux ;
* un champ refusé par Koillection était consigné dans le journal du serveur et
  nulle part ailleurs, si bien que la fiche amputée passait inaperçue.
"""

import asyncio

import pytest

from app.config import Settings
from app.history import History
from app.importer import Importer
from app.koillection import KoillectionClient
from app.models import AddRequest, KoiCollection

COLLECTION = KoiCollection(
    id="col-1", iri="/api/collections/col-1", title="Livres lus", path="Livres lus"
)
ISBN = "9782258201804"
TITRE = "Trois vies par semaine"


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def client_avec(items: list[dict], champs: dict[str, object]) -> KoillectionClient:
    """Un client dont la collection contient `items`, chacun avec ses champs.

    ``champs`` associe un identifiant d'item soit à sa liste de données, soit à
    un code HTTP d'erreur pour simuler des champs illisibles.
    """
    client = KoillectionClient(Settings())

    async def fake_request(method, path, *, params=None, **kwargs):
        if path.endswith("/items"):
            page = (params or {}).get("page", 1)
            return FakeResponse({"hydra:member": items if page == 1 else []})
        if path.endswith("/data"):
            item_id = path.split("/")[3]
            contenu = champs.get(item_id, [])
            if isinstance(contenu, int):
                return FakeResponse({"detail": "boum"}, status_code=contenu)
            return FakeResponse({"hydra:member": contenu})
        raise AssertionError(f"appel inattendu : {method} {path}")

    client.request = fake_request
    return client


# ── find_duplicate ────────────────────────────────────────────────────


async def test_un_item_du_meme_nom_sans_isbn_est_un_doublon():
    """Le cœur du bug : la fiche laissée sans ISBN par un ajout raté.

    Le nom concorde, aucun ISBN ne le contredit — c'est le même livre. Avant,
    l'absence d'ISBN valait « autre livre », et chaque nouveau scan en
    fabriquait une copie de plus, sans le moindre message.
    """
    items = [{"id": "i1", "name": TITRE}]
    client = client_avec(items, {"i1": [{"label": "Auteur", "value": "Michel Bussi"}]})
    trouve = await client.find_duplicate(COLLECTION, ISBN, TITRE)
    assert trouve is not None and trouve["id"] == "i1"


async def test_un_isbn_different_ecarte_lhomonyme():
    """Deux livres différents peuvent porter le même titre : l'ISBN tranche."""
    items = [{"id": "i1", "name": TITRE}]
    client = client_avec(items, {"i1": [{"label": "ISBN", "value": "9782070368228"}]})
    assert await client.find_duplicate(COLLECTION, ISBN, TITRE) is None


async def test_lisbn_qui_concorde_lemporte_sur_lhomonyme_muet():
    items = [{"id": "muet", "name": TITRE}, {"id": "bon", "name": TITRE}]
    client = client_avec(
        items,
        {"muet": [{"label": "Auteur", "value": "Michel Bussi"}],
         "bon": [{"label": "ISBN", "value": "978-2-258-20180-4"}]},
    )
    trouve = await client.find_duplicate(COLLECTION, ISBN, TITRE)
    assert trouve is not None and trouve["id"] == "bon"


async def test_un_isbn_vide_ne_vaut_pas_confirmation():
    """Un champ ISBN présent mais vide ne prouve rien : c'est un item muet."""
    items = [{"id": "i1", "name": TITRE}]
    client = client_avec(items, {"i1": [{"label": "ISBN", "value": ""}]})
    trouve = await client.find_duplicate(COLLECTION, ISBN, TITRE)
    assert trouve is not None and trouve["id"] == "i1"


async def test_des_champs_illisibles_font_pencher_vers_la_mise_en_garde():
    """Koillection qui refuse de livrer les champs : le doute profite à l'alerte."""
    items = [{"id": "i1", "name": TITRE}]
    client = client_avec(items, {"i1": 500})
    trouve = await client.find_duplicate(COLLECTION, ISBN, TITRE)
    assert trouve is not None and trouve["id"] == "i1"


async def test_un_autre_titre_nest_pas_un_doublon():
    items = [{"id": "i1", "name": "Nouvelle Babel"}]
    client = client_avec(items, {"i1": [{"label": "ISBN", "value": ISBN}]})
    assert await client.find_duplicate(COLLECTION, ISBN, TITRE) is None


async def test_le_nom_est_compare_sans_accent_ni_ponctuation():
    items = [{"id": "i1", "name": "L'Été d'avant"}]
    client = client_avec(items, {"i1": [{"label": "ISBN", "value": ISBN}]})
    trouve = await client.find_duplicate(COLLECTION, ISBN, "l ete davant")
    assert trouve is not None


# ── add_datum ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(("code", "attendu"), [(201, True), (200, True), (422, False), (500, False)])
async def test_un_champ_refuse_est_signale_a_lappelant(code, attendu):
    client = KoillectionClient(Settings())

    async def fake_request(method, path, **kwargs):
        return FakeResponse({}, status_code=code)

    client.request = fake_request
    assert await client.add_datum("/api/items/i1", "ISBN", ISBN, "text", 0) is attendu


# ── L'importateur de bout en bout ─────────────────────────────────────


class FauxKoillection(KoillectionClient):
    """Koillection en mémoire, servi par le **vrai** client.

    Seule la couche HTTP est simulée : la recherche de doublon, l'écriture des
    champs et la vérification d'existence exécutées ici sont celles du code de
    production, pas une imitation.
    """

    def __init__(self, latence: float = 0.0) -> None:
        super().__init__(Settings())
        self.items: list[dict] = []
        self.champs: dict[str, list[dict]] = {}
        self.latence = latence
        self.refuse: set[str] = set()
        self._collections = [COLLECTION]
        self._collections_at = float("inf")

    async def request(self, method, path, *, json_body=None, params=None, **kwargs):
        if method == "GET" and path.endswith("/items"):
            # L'ordre compte : la liste part telle qu'elle est à cet instant,
            # puis vient le temps du trajet réseau. Lire après avoir dormi
            # sérialiserait les appels et la course ne se jouerait jamais.
            instantane = [dict(item) for item in self.items]
            await asyncio.sleep(self.latence)
            page = (params or {}).get("page", 1)
            return FakeResponse({"hydra:member": instantane if page == 1 else []})

        if method == "GET" and path.endswith("/data"):
            item_id = path.split("/")[3]
            return FakeResponse({"hydra:member": self.champs.get(item_id, [])})

        if method == "GET" and path.startswith("/api/items/"):
            item_id = path.rsplit("/", 1)[-1]
            if any(item["id"] == item_id for item in self.items):
                return FakeResponse({"id": item_id})
            return FakeResponse({"detail": "Not Found"}, status_code=404)

        if method == "POST" and path == "/api/items":
            item = {"id": f"item-{len(self.items) + 1}", "name": json_body["name"]}
            self.items.append(item)
            return FakeResponse(item, status_code=201)

        if method == "POST" and path == "/api/data":
            if json_body["label"] in self.refuse:
                return FakeResponse({"detail": "refusé"}, status_code=422)
            item_id = json_body["item"].rsplit("/", 1)[-1]
            self.champs.setdefault(item_id, []).append(
                {"label": json_body["label"], "value": json_body["value"]}
            )
            return FakeResponse({"id": "d1"}, status_code=201)

        if path == "/api/tags":
            return FakeResponse({"hydra:member": []} if method == "GET" else {"id": "t1"})

        raise AssertionError(f"appel inattendu : {method} {path}")


def make_importer(koillection, history) -> Importer:
    settings = Settings()
    settings.upload_cover = False
    settings.genres_as_tags = False
    return Importer(settings, koillection, history, lookup=None)


def demande(**extra) -> AddRequest:
    return AddRequest(
        isbn13=ISBN, title=TITRE, authors=["Michel Bussi"], collection="Livres lus", **extra
    )


@pytest.fixture()
def historique(tmp_path):
    return History(tmp_path / "history.sqlite3")


async def test_deux_validations_simultanees_ne_creent_quun_item(historique):
    """Le double appui sur « Ajouter », ou la touche Entrée du téléphone."""
    await historique.init()
    koillection = FauxKoillection(latence=0.05)
    importer = make_importer(koillection, historique)

    reponses = await asyncio.gather(*[importer.add(demande()) for _ in range(4)])

    assert len(koillection.items) == 1
    assert sum(1 for r in reponses if r.ok) == 1
    assert sum(1 for r in reponses if r.duplicate) == 3


async def test_deux_livres_differents_restent_traites_en_parallele(historique):
    await historique.init()
    koillection = FauxKoillection(latence=0.05)
    importer = make_importer(koillection, historique)

    autre = AddRequest(
        isbn13="9782070368228", title="1984", authors=["George Orwell"], collection="Livres lus"
    )
    await asyncio.gather(importer.add(demande()), importer.add(autre))
    assert len(koillection.items) == 2


async def test_un_champ_refuse_est_remonte_a_linterface(historique):
    """Une fiche amputée doit se voir : c'est elle qui échappait aux contrôles."""
    await historique.init()
    koillection = FauxKoillection()
    koillection.refuse = {"ISBN"}
    importer = make_importer(koillection, historique)

    reponse = await importer.add(demande())
    assert reponse.ok is True
    assert reponse.warnings == ["ISBN"]


async def test_une_fiche_sans_isbn_nest_pas_ajoutee_deux_fois(historique):
    """Le scénario exact de l'import raté, joué de bout en bout."""
    await historique.init()
    koillection = FauxKoillection()
    koillection.refuse = {"ISBN"}
    importer = make_importer(koillection, historique)

    premier = await importer.add(demande())
    second = await importer.add(demande())

    assert premier.ok is True
    assert second.duplicate is True
    assert len(koillection.items) == 1


async def test_une_fiche_renommee_reste_reconnue_par_lhistorique(historique):
    """L'historique local garde l'ISBN, même quand le nom de l'item a changé."""
    await historique.init()
    koillection = FauxKoillection()
    importer = make_importer(koillection, historique)

    await importer.add(demande())
    koillection.items[0]["name"] = "Bussi - Trois vies par semaine"

    reponse = await importer.add(demande())
    assert reponse.duplicate is True
    assert len(koillection.items) == 1


async def test_un_livre_supprime_de_koillection_peut_etre_rescanne(historique):
    """Le filet de l'historique ne doit pas bloquer un livre qui n'existe plus."""
    await historique.init()
    koillection = FauxKoillection()
    importer = make_importer(koillection, historique)

    await importer.add(demande())
    koillection.items.clear()          # l'utilisateur l'a supprimé dans Koillection

    reponse = await importer.add(demande())
    assert reponse.ok is True
    assert len(koillection.items) == 1


async def test_un_second_exemplaire_reste_possible_en_forcant(historique):
    await historique.init()
    koillection = FauxKoillection()
    importer = make_importer(koillection, historique)

    await importer.add(demande())
    reponse = await importer.add(demande(force=True))

    assert reponse.ok is True
    assert len(koillection.items) == 2
