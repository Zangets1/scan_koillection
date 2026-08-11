"""Client Koillection : pagination et fraîcheur du cache."""

import httpx
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


# ── Diagnostic de la chaîne de connexion ──────────────────────────────


async def test_diagnostic_signale_les_variables_manquantes(monkeypatch):
    monkeypatch.setenv("KOILLECTION_URL", "")
    monkeypatch.setenv("KOILLECTION_USERNAME", "")
    monkeypatch.setenv("KOILLECTION_PASSWORD", "")
    steps = await KoillectionClient(Settings()).diagnose()
    assert [s["ok"] for s in steps] == [False]
    assert "KOILLECTION_URL" in steps[0]["detail"]


async def test_diagnostic_distingue_un_compte_vide_dune_panne(monkeypatch):
    """Le cas piégeux : tout fonctionne, mais le compte n'a aucune collection."""
    monkeypatch.setenv("KOILLECTION_URL", "http://koillection")
    monkeypatch.setenv("KOILLECTION_USERNAME", "scanner")
    monkeypatch.setenv("KOILLECTION_PASSWORD", "secret")

    client = client_with_pages([[]])
    client._client = object()  # présence suffisante, les appels sont simulés

    async def fake_get(path, **kwargs):
        return FakeResponse({}, 200)

    client._client = type("C", (), {"get": staticmethod(fake_get)})()

    async def fake_auth():
        return "jeton"

    client._authenticate = fake_auth

    steps = await client.diagnose()
    labels = {s["label"]: s for s in steps}
    assert labels["Koillection joignable"]["ok"] is True
    assert labels["Identifiants acceptés"]["ok"] is True
    assert labels["Collections visibles"]["ok"] is False
    # Le message doit orienter vers la vraie cause, pas vers une panne réseau.
    assert "scanner" in labels["Collections visibles"]["detail"]
    assert "collection appartient à son créateur" in labels["Collections visibles"]["detail"]


@pytest.mark.parametrize(
    ("message", "attendu"),
    [
        ("[Errno -2] Name or service not known", "même réseau Docker"),
        ("nodename nor servname provided", "même réseau Docker"),
        ("All connection attempts failed", "Rien ne répond"),
        ("Connection refused", "Rien ne répond"),
    ],
)
def test_les_erreurs_reseau_sont_traduites_en_cause_probable(message, attendu):
    from app.koillection import _explain_network_error

    detail = _explain_network_error(httpx.ConnectError(message), "http://koillection:80")
    assert attendu in detail


def test_un_nom_introuvable_est_cite_dans_le_message():
    from app.koillection import _explain_network_error

    detail = _explain_network_error(
        httpx.ConnectError("[Errno -2] Name or service not known"), "http://koillection:80"
    )
    assert "« koillection »" in detail
