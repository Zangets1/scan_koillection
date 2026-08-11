"""Comportement du service de recherche : parallélisme, plafond de temps, cache."""

import asyncio
import time

import httpx
import pytest

from app.config import Settings
from app.lookup import LookupService
from app.models import BookMeta
from app.providers.base import Provider


class FakeProvider(Provider):
    def __init__(self, name: str, delay: float = 0.0, meta: BookMeta | None = None) -> None:
        self.name = name
        self.label = name.upper()
        self.delay = delay
        self.meta = meta
        self.calls = 0

    async def fetch(self, client: httpx.AsyncClient, isbn13: str) -> BookMeta | None:
        self.calls += 1
        await asyncio.sleep(self.delay)
        return self.meta


def book(title: str, **kwargs) -> BookMeta:
    return BookMeta(isbn13="9782070368228", title=title, **kwargs)


async def build(providers, deadline: float = 4.0) -> LookupService:
    settings = Settings()
    settings.lookup_deadline = deadline
    service = LookupService(settings)
    await service.startup()
    service.providers = providers
    return service


@pytest.mark.asyncio
async def test_les_fournisseurs_sont_interroges_en_parallele():
    lents = [FakeProvider(f"p{i}", delay=0.25, meta=book("1984")) for i in range(4)]
    service = await build(lents)
    started = time.monotonic()
    result = await service.lookup("9782070368228")
    elapsed = time.monotonic() - started
    await service.shutdown()

    assert result.found
    # En séquentiel il aurait fallu 1 s ; en parallèle, à peine plus de 0,25 s.
    assert elapsed < 0.6


@pytest.mark.asyncio
async def test_un_fournisseur_trop_lent_ne_bloque_pas_la_reponse():
    rapide = FakeProvider("rapide", delay=0.05, meta=book("1984", publisher="Gallimard"))
    trainard = FakeProvider("trainard", delay=5.0, meta=book("1984", synopsis="jamais reçu"))
    service = await build([rapide, trainard], deadline=0.4)

    started = time.monotonic()
    result = await service.lookup("9782070368228")
    elapsed = time.monotonic() - started
    await service.shutdown()

    assert elapsed < 1.0
    assert result.found
    assert result.book.publisher == "Gallimard"
    assert result.book.synopsis is None
    assert result.providers["RAPIDE"] == "trouvé"
    assert result.providers["TRAINARD"] == "trop lent"


@pytest.mark.asyncio
async def test_la_priorite_suit_lordre_configure_pas_lordre_darrivee():
    # Le fournisseur prioritaire répond en dernier : il doit tout de même gagner.
    prioritaire = FakeProvider("bnf", delay=0.2, meta=book("Titre BnF"))
    secondaire = FakeProvider("autre", delay=0.01, meta=book("Titre secondaire"))
    service = await build([prioritaire, secondaire])
    result = await service.lookup("9782070368228")
    await service.shutdown()
    assert result.book.title == "Titre BnF"


@pytest.mark.asyncio
async def test_un_fournisseur_en_erreur_est_signale_sans_tout_casser():
    class Casse(FakeProvider):
        async def fetch(self, client, isbn13):
            raise ValueError("réponse inattendue")

    service = await build([Casse("casse"), FakeProvider("ok", meta=book("1984"))])
    result = await service.lookup("9782070368228")
    await service.shutdown()
    assert result.found
    assert result.providers["CASSE"] == "réponse inexploitable"


@pytest.mark.asyncio
async def test_le_cache_evite_de_reinterroger_les_catalogues():
    provider = FakeProvider("bnf", meta=book("1984"))
    service = await build([provider])
    await service.lookup("9782070368228")
    await service.lookup("9782070368228")
    await service.shutdown()
    assert provider.calls == 1
