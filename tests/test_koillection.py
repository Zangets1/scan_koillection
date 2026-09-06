"""Client Koillection : pagination et fraîcheur du cache."""

import httpx
import pytest

from app import koillection as koi_module
from app.config import Settings
from app.koillection import KoillectionClient, KoillectionError


class FakeResponse:
    def __init__(self, payload, status_code: int = 200, text: str | None = None) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload) if text is None else text

    def json(self):
        if self._payload is None:  # corps non JSON : page d'erreur HTML, corps vide…
            raise ValueError("réponse non JSON")
        return self._payload


class FakeHttp:
    """Faux ``httpx.AsyncClient`` qui compte les demandes de jeton.

    La dernière réponse fournie est répétée : un serveur en panne le reste tant
    qu'on ne l'a pas réparé.
    """

    def __init__(self, *reponses: FakeResponse) -> None:
        self.reponses = list(reponses)
        self.jetons = 0

    async def post(self, path, **kwargs):
        assert path == "/api/authentication_token"
        self.jetons += 1
        return self.reponses[min(self.jetons - 1, len(self.reponses) - 1)]

    async def get(self, path, **kwargs):
        return FakeResponse({}, 200)

    async def request(self, method, path, **kwargs):
        return FakeResponse([], 200)


def client_avec_serveur(*reponses: FakeResponse) -> tuple[KoillectionClient, FakeHttp]:
    http = FakeHttp(*reponses)
    client = KoillectionClient(Settings())
    client._client = http
    return client, http


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


# ── Authentification : nommer la panne, pas la configuration ──────────


def test_une_erreur_500_ne_renvoie_pas_a_la_configuration():
    """Le cas signalé : GET /api répond 200, POST authentication_token répond 500.

    L'ancien message — « Vérifiez KOILLECTION_URL » — envoyait retourner une
    adresse qui vient précisément de répondre.
    """
    from app.koillection import _explain_auth_failure

    detail = _explain_auth_failure(
        FakeResponse({"detail": "Unable to create a signed JWT from the given configuration."}, 500)
    )
    assert "KOILLECTION_URL" not in detail
    assert "lexik:jwt:generate-keypair" in detail
    # Le message du serveur, quand il en donne un, vaut tous les conseils.
    assert "Unable to create a signed JWT" in detail


def test_une_erreur_404_met_en_cause_ladresse():
    from app.koillection import _explain_auth_failure

    detail = _explain_auth_failure(FakeResponse({}, 404))
    assert "KOILLECTION_URL" in detail


def test_une_passerelle_en_panne_est_distinguee_du_serveur():
    from app.koillection import _explain_auth_failure

    detail = _explain_auth_failure(FakeResponse({}, 502))
    assert "intermédiaire" in detail
    assert "lexik:jwt:generate-keypair" not in detail


def test_une_page_derreur_html_nest_pas_recopiee():
    """Citer 200 caractères de HTML noierait le conseil qui suit."""
    from app.koillection import _server_detail

    html = "<!DOCTYPE html><html><head><title>Oops</title></head><body>…</body></html>"
    assert _server_detail(FakeResponse(None, 500, text=html)) == ""


async def test_un_mot_de_passe_refuse_reste_nomme_comme_tel():
    client, _ = client_avec_serveur(FakeResponse({}, 401))
    with pytest.raises(KoillectionError) as refus:
        await client._ensure_token()
    assert "Identifiants Koillection refusés" in str(refus.value)


async def test_un_200_sans_jeton_designe_lintermediaire():
    """Une page d'accueil de reverse proxy répond 200 : ce n'est pas Koillection."""
    client, _ = client_avec_serveur(FakeResponse({"message": "Bienvenue"}, 200))
    with pytest.raises(KoillectionError) as sans_jeton:
        await client._ensure_token()
    assert "sans jeton JWT" in str(sans_jeton.value)


async def test_une_panne_nest_pas_retentee_a_chaque_requete():
    """Chaque affichage de page redemandait un jeton à un serveur en panne."""
    client, http = client_avec_serveur(FakeResponse({}, 500))

    for _ in range(3):
        with pytest.raises(KoillectionError):
            await client.collections()

    assert http.jetons == 1


async def test_la_temporisation_expire(monkeypatch):
    client, http = client_avec_serveur(FakeResponse({}, 500))
    with pytest.raises(KoillectionError):
        await client.collections()

    monkeypatch.setattr(koi_module, "AUTH_RETRY_DELAY", 0.0)
    with pytest.raises(KoillectionError):
        await client.collections()
    assert http.jetons == 2


async def test_un_rafraichissement_explicite_retente_tout_de_suite():
    """L'utilisateur répare Koillection puis clique « Recharger » : ça doit repartir."""
    client, http = client_avec_serveur(FakeResponse({}, 500), FakeResponse({"token": "jwt"}, 200))

    with pytest.raises(KoillectionError):
        await client.collections()

    assert await client.collections(refresh=True) == []
    assert http.jetons == 2


async def test_un_rafraichissement_ne_gaspille_pas_un_jeton_encore_bon():
    """Court-circuiter la temporisation, oui ; jeter un jeton valide, non."""
    client, http = client_avec_serveur(FakeResponse({"token": "jwt"}, 200))

    assert await client.collections() == []
    assert await client.collections(refresh=True) == []
    assert http.jetons == 1


async def test_le_diagnostic_ne_met_pas_en_cause_les_identifiants_sur_une_panne(monkeypatch):
    monkeypatch.setenv("KOILLECTION_URL", "http://koillection")
    monkeypatch.setenv("KOILLECTION_USERNAME", "scanner")
    monkeypatch.setenv("KOILLECTION_PASSWORD", "secret")

    client, _ = client_avec_serveur(FakeResponse({}, 500))
    steps = await client.diagnose()

    labels = {s["label"]: s for s in steps}
    assert labels["Koillection joignable"]["ok"] is True
    # Le mot de passe n'a pas été examiné : ne pas laisser croire qu'il est en cause.
    assert "Identifiants acceptés" not in labels
    assert labels["API d'authentification"]["ok"] is False
    assert "lexik:jwt:generate-keypair" in labels["API d'authentification"]["detail"]


async def test_le_diagnostic_retente_meme_apres_un_echec_recent(monkeypatch):
    """« Diagnostiquer la connexion » interroge le serveur, il ne relit pas un verdict."""
    monkeypatch.setenv("KOILLECTION_URL", "http://koillection")
    monkeypatch.setenv("KOILLECTION_USERNAME", "scanner")
    monkeypatch.setenv("KOILLECTION_PASSWORD", "secret")

    client, http = client_avec_serveur(FakeResponse({}, 500))
    with pytest.raises(KoillectionError):
        await client.collections()

    await client.diagnose()
    assert http.jetons == 2
