"""Tests de l'API HTTP, avec des fournisseurs et un Koillection simulés."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.models import BookMeta, LookupResponse


class FakeLookup:
    def __init__(self, response: LookupResponse) -> None:
        self.response = response
        self.providers = []
        self.client = httpx.AsyncClient()

    async def lookup(self, isbn13: str, use_cache: bool = True) -> LookupResponse:
        return self.response


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(main.app) as test_client:
        yield test_client


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_config_expose_letat(client):
    payload = client.get("/api/config").json()
    assert payload["version"]
    assert "koillection_configured" in payload


def test_isbn_invalide_renvoie_422(client):
    response = client.get("/api/lookup/1234")
    assert response.status_code == 422
    assert "10 ou 13" in response.json()["detail"]


def test_isbn_non_livre_refuse(client):
    response = client.get("/api/lookup/3560070123452")
    assert response.status_code == 422
    assert "978/979" in response.json()["detail"]


def test_lookup_renvoie_le_livre(client):
    book = BookMeta(isbn13="9782070368228", title="1984", authors=["George Orwell"])
    client.app.state.lookup = FakeLookup(
        LookupResponse(found=True, isbn13="9782070368228", book=book, providers={"BnF": "trouvé"})
    )
    payload = client.get("/api/lookup/978-2-07-036822-8").json()
    assert payload["found"] is True
    assert payload["book"]["title"] == "1984"


def test_lookup_sans_resultat_invite_a_la_saisie(client):
    client.app.state.lookup = FakeLookup(
        LookupResponse(found=False, isbn13="9791234567896", message="Aucun catalogue ne connaît cet ISBN.")
    )
    payload = client.get("/api/lookup/9791234567896").json()
    assert payload["found"] is False
    assert "Aucun catalogue" in payload["message"]


def test_la_page_est_servie(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Scan" in response.text


def test_route_api_inconnue_reste_en_json(client):
    response = client.get("/api/n-existe-pas")
    assert response.status_code == 404
    assert response.json()["detail"]
