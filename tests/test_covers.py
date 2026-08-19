"""Résolution des couvertures : ordre des sources, refus, et téléchargement unique."""

import hashlib

import httpx
import pytest

from app import covers

#: Un JPEG minimal, assez gros pour passer le seuil de MIN_COVER_BYTES.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 4000

#: Ce qu'OpenLibrary sert quand elle n'a pas l'image : un GIF transparent.
GIF_VIDE = b"GIF89a" + b"\x00" * 37


@pytest.fixture(autouse=True)
def cache_vide():
    covers.clear_cache()
    yield
    covers.clear_cache()


def client(reponses: dict[str, httpx.Response]) -> httpx.AsyncClient:
    """Client dont chaque URL rend la réponse prévue, et qui compte les appels."""
    appels: list[str] = []

    def repondre(request: httpx.Request) -> httpx.Response:
        appels.append(str(request.url))
        return reponses.get(str(request.url), httpx.Response(404))

    transport = httpx.MockTransport(repondre)
    fabrique = httpx.AsyncClient(transport=transport)
    fabrique.appels = appels  # type: ignore[attr-defined]
    return fabrique


def image(contenu: bytes = JPEG, type_mime: str = "image/jpeg") -> httpx.Response:
    return httpx.Response(200, content=contenu, headers={"content-type": type_mime})


# ----------------------------------------------------------------------
# Ordre et composition de la liste
# ----------------------------------------------------------------------
def test_epagine_passe_devant_les_catalogues():
    liste = covers.candidates("9782344058190", ["https://catalogue.bnf.fr/couverture?x"])
    assert liste[0] == "https://images.epagine.fr/190/9782344058190_1_75.jpg"
    assert liste[1] == "https://catalogue.bnf.fr/couverture?x"
    assert liste[-1] == "https://covers.openlibrary.org/b/isbn/9782344058190-L.jpg"


def test_une_meme_url_n_est_pas_essayee_deux_fois():
    fallback = "https://covers.openlibrary.org/b/isbn/9782344058190-L.jpg"
    liste = covers.candidates("9782344058190", [fallback, fallback])
    assert liste.count(fallback) == 1


def test_un_code_qui_n_est_pas_un_ean_n_a_pas_d_url_epagine():
    # Le chemin se construit sur les treize chiffres : sans eux, pas de candidat.
    assert covers.epagine_url("978207036822X") is None
    assert covers.epagine_url("2070368220") is None


# ----------------------------------------------------------------------
# Liste blanche
# ----------------------------------------------------------------------
def test_la_liste_blanche_couvre_epagine_et_ferme_le_reste():
    assert covers.is_allowed("https://images.epagine.fr/190/9782344058190_1_75.jpg")
    # Sans liste blanche, /api/cover relaierait n'importe quoi depuis le NAS.
    assert not covers.is_allowed("http://192.168.1.10/admin")
    assert not covers.is_allowed("file:///etc/passwd")


@pytest.mark.asyncio
async def test_une_url_hors_liste_blanche_n_est_meme_pas_appelee():
    hostile = "http://192.168.1.10/couverture.jpg"
    bonne = "https://images.epagine.fr/190/9782344058190_1_75.jpg"
    async with client({bonne: image()}) as http:
        cover = await covers.resolve(http, [hostile, bonne])
        assert cover is not None
        assert http.appels == [bonne]


# ----------------------------------------------------------------------
# Ce que les services appellent « pas d'image »
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_les_facons_de_dire_non_sont_toutes_ecartees():
    """Page HTML de la BnF, GIF vide d'OpenLibrary, image trop petite."""
    bnf = "https://catalogue.bnf.fr/couverture?x"
    openlibrary = "https://covers.openlibrary.org/b/isbn/9782344058190-L.jpg"
    minuscule = "https://images.isbndb.com/covers/1.jpg"
    vraie = "https://images.epagine.fr/190/9782344058190_1_75.jpg"
    reponses = {
        bnf: httpx.Response(500, content=b"<html>erreur</html>",
                            headers={"content-type": "text/html"}),
        openlibrary: image(GIF_VIDE, "image/gif"),
        minuscule: image(b"\xff\xd8" + b"\x00" * 100),
        vraie: image(),
    }
    async with client(reponses) as http:
        cover = await covers.resolve(http, [bnf, openlibrary, minuscule, vraie])
    assert cover is not None and cover.url == vraie
    assert cover.extension == ".jpg"


@pytest.mark.asyncio
async def test_une_image_de_remplacement_n_est_pas_une_couverture(monkeypatch):
    """« Couverture indisponible » est une vraie image, de bonne taille et de bon type.

    Seule son empreinte la distingue : c'est la même pour tous les livres.
    """
    remplacement = b"\xff\xd8\xff\xe0" + b"\x01" * 5000
    monkeypatch.setitem(
        covers.PLACEHOLDERS, hashlib.md5(remplacement).hexdigest(), "service d'essai"
    )
    faux = "https://images.epagine.fr/190/9782344058190_1_75.jpg"
    vrai = "https://covers.openlibrary.org/b/isbn/9782344058190-L.jpg"
    async with client({faux: image(remplacement), vrai: image()}) as http:
        cover = await covers.resolve(http, [faux, vrai])
    assert cover is not None and cover.url == vrai


@pytest.mark.asyncio
async def test_aucune_source_ne_repond():
    async with client({}) as http:
        assert await covers.resolve(http, ["https://images.epagine.fr/190/x.jpg"]) is None


# ----------------------------------------------------------------------
# Le téléchargement unique
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_la_couverture_affichee_n_est_pas_retelechargee_a_l_ajout():
    """La fiche puis l'ajout résolvent la même image à quelques secondes d'écart."""
    url = "https://images.epagine.fr/190/9782344058190_1_75.jpg"
    async with client({url: image()}) as http:
        affichee = await covers.resolve(http, [url])
        televersee = await covers.resolve(http, [url])
        assert http.appels == [url]
    assert affichee is not None and televersee is not None
    assert televersee.content == affichee.content


@pytest.mark.asyncio
async def test_une_image_trop_lourde_n_encombre_pas_la_memoire():
    """Le cache tient dans la mémoire d'un NAS : au-delà, on préfère retélécharger."""
    url = "https://images.epagine.fr/190/9782344058190_1_75.jpg"
    lourde = b"\xff\xd8\xff\xe0" + b"\x00" * (3 * 1024 * 1024)
    async with client({url: image(lourde)}) as http:
        await covers.resolve(http, [url])
        await covers.resolve(http, [url])
        assert http.appels == [url, url]
