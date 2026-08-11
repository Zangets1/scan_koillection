"""Client Koillection : pagination et fraîcheur du cache."""

import pytest

from app import koillection as koi_module
from app.config import Settings
from app.koillection import KoillectionClient


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def client_with_pages(pages: list[list[dict]]) -> KoillectionClient:
    """Un client dont chaque appel paginé renvoie la page suivante de `pages`."""
    client = KoillectionClient(Settings())
    client.requests: list[int] = []

    async def fake_request(method, path, *, params=None, **kwargs):
        page = (params or {}).get("page", 1)
        client.requests.append(page)
        return FakeResponse(pages[page - 1] if page <= len(pages) else [])

    client.request = fake_request
    return client


async def test_toutes_les_pages_sont_lues():
    # 30 puis 12 : la deuxième page ne doit pas être ignorée.
    pages = [
        [{"id": f"a{i}", "title": f"Collection {i}"} for i in range(30)],
        [{"id": f"b{i}", "title": f"Collection {30 + i}"} for i in range(12)],
    ]
    client = client_with_pages(pages)
    assert len(await client.collections()) == 42


async def test_une_page_courte_ninterrompt_pas_la_lecture():
    # Rien ne garantit que le serveur pagine par 30 : une page plus courte que
    # prévu ne doit pas faire croire que la liste est terminée.
    pages = [
        [{"id": f"a{i}", "title": f"C{i}"} for i in range(15)],
        [{"id": f"b{i}", "title": f"D{i}"} for i in range(15)],
        [{"id": "c0", "title": "Dernière"}],
    ]
    client = client_with_pages(pages)
    collections = await client.collections()
    assert len(collections) == 31
    assert any(c.title == "Dernière" for c in collections)


async def test_une_collection_creee_apres_le_demarrage_finit_par_apparaitre(monkeypatch):
    """C'est le cas signalé : créer une collection pendant que le scanner tourne."""
    etat = [[{"id": "a", "title": "Livres"}], []]
    client = client_with_pages(etat)

    assert [c.title for c in await client.collections()] == ["Livres"]

    # L'utilisateur ajoute « Mangas » depuis Koillection.
    etat[0] = [{"id": "a", "title": "Livres"}, {"id": "b", "title": "Mangas"}]

    # Tant que le cache est frais, la liste ne bouge pas : c'est voulu, on
    # n'interroge pas l'API à chaque affichage de page.
    assert len(await client.collections()) == 1

    # Passé le délai, elle se resynchronise toute seule.
    monkeypatch.setattr(koi_module, "CACHE_TTL", 0.0)
    assert [c.title for c in await client.collections()] == ["Livres", "Mangas"]


async def test_le_rafraichissement_explicite_court_circuite_le_cache():
    etat = [[{"id": "a", "title": "Livres"}], []]
    client = client_with_pages(etat)
    await client.collections()
    etat[0] = [{"id": "a", "title": "Livres"}, {"id": "b", "title": "Mangas"}]
    assert len(await client.collections(refresh=True)) == 2


@pytest.mark.parametrize(
    ("titre", "reference"),
    [("Livres", "Livres"), ("Livres", "livres"), ("Livres", "/api/collections/a")],
)
async def test_recherche_de_collection_par_titre_ou_iri(titre, reference):
    client = client_with_pages([[{"id": "a", "title": titre}], []])
    trouvee = await client.find_collection(reference)
    assert trouvee is not None and trouvee.id == "a"


async def test_le_chemin_hierarchique_est_reconstruit():
    pages = [
        [
            {"id": "a", "title": "Livres"},
            {"id": "b", "title": "Mangas", "parent": "/api/collections/a"},
            {"id": "c", "title": "One Piece", "parent": "/api/collections/b"},
        ],
        [],
    ]
    client = client_with_pages(pages)
    chemins = {c.title: c.path for c in await client.collections()}
    assert chemins["One Piece"] == "Livres / Mangas / One Piece"
