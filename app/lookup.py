"""Interrogation parallèle des catalogues et fusion des résultats."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from collections import OrderedDict

import httpx

from . import covers
from . import isbn as isbn_utils
from . import series as series_utils
from .config import Settings
from .models import BookMeta, LookupResponse
from .providers import Provider, build_providers
from .providers.base import dedupe

logger = logging.getLogger(__name__)

USER_AGENT = (
    "scan-koillection/1.0 (+https://github.com/zangets1/scan_koillection) "
    "recherche de metadonnees livre par ISBN"
)


class _TTLCache:
    """Petit cache mémoire LRU + TTL, suffisant pour un usage domestique."""

    def __init__(self, maxsize: int, ttl: int) -> None:
        self.maxsize = max(maxsize, 1)
        self.ttl = ttl
        self._store: OrderedDict[str, tuple[float, LookupResponse]] = OrderedDict()

    def get(self, key: str) -> LookupResponse | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if self.ttl > 0 and time.monotonic() - stored_at > self.ttl:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: LookupResponse) -> None:
        if self.ttl <= 0:
            return
        self._store[key] = (time.monotonic(), value)
        self._store.move_to_end(key)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


class LookupService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.providers: list[Provider] = build_providers(settings)
        self._cache = _TTLCache(settings.cache_size, settings.cache_ttl)
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.provider_timeout),
            headers={"User-Agent": USER_AGENT, "Accept-Language": "fr,en;q=0.8"},
            follow_redirects=True,
        )

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:  # pragma: no cover - garde-fou
            raise RuntimeError("LookupService.startup() n'a pas été appelé")
        return self._client

    async def lookup(self, isbn13: str, use_cache: bool = True) -> LookupResponse:
        if use_cache:
            cached = self._cache.get(isbn13)
            if cached is not None:
                return cached

        started = time.monotonic()
        statuses, metas = await self._query_providers(isbn13)

        elapsed = int((time.monotonic() - started) * 1000)
        if not metas:
            response = LookupResponse(
                found=False,
                isbn13=isbn13,
                providers=statuses,
                elapsed_ms=elapsed,
                message="Aucun catalogue ne connaît cet ISBN. Saisissez le titre et l'auteur à la main.",
            )
        else:
            response = LookupResponse(
                found=True,
                isbn13=isbn13,
                book=merge(metas, isbn13),
                providers=statuses,
                elapsed_ms=elapsed,
            )
        self._cache.set(isbn13, response)
        return response

    async def _query_providers(
        self, isbn13: str
    ) -> tuple[dict[str, str], list[BookMeta]]:
        """Interroge tous les catalogues en parallèle, sous un plafond de temps.

        Les fournisseurs sont indépendants : rien ne justifie de faire attendre
        l'utilisateur, code-barres en main devant son étagère, parce qu'un
        catalogue secondaire est lent. Passé le délai, on répond avec ce qui est
        arrivé et les retardataires sont signalés comme tels dans l'interface.

        Encore faut-il qu'ils aient une chance de répondre : le groupe
        d'enregistrement de l'ISBN désigne l'agence qui a enregistré l'éditeur,
        donc l'aire linguistique du livre. Interroger la BnF pour un ISBN 978-0
        ouvre une connexion pour rien. Ce tri est une lecture de cinq chiffres,
        et il retire deux candidats au titre de « fournisseur le plus lent ».
        """
        group = isbn_utils.registration_group(isbn13)
        tasks = {
            asyncio.create_task(self._fetch_one(provider, isbn13)): provider
            for provider in self.providers
            if provider.handles(group)
        }
        if not tasks:
            return {}, []

        done, pending = await asyncio.wait(tasks, timeout=self.settings.lookup_deadline)
        for task in pending:
            task.cancel()
        if pending:
            logger.info(
                "ISBN %s : %s hors délai (%.1f s)",
                isbn13,
                ", ".join(tasks[task].label for task in pending),
                self.settings.lookup_deadline,
            )

        statuses: dict[str, str] = {}
        results: dict[str, BookMeta] = {}
        for task, provider in tasks.items():
            if task not in done:
                statuses[provider.label] = "trop lent"
                continue
            meta, status = task.result()
            statuses[provider.label] = status
            if meta is not None:
                results[provider.name] = meta

        # L'ordre de PROVIDERS fait foi pour la fusion, pas l'ordre d'arrivée.
        metas = [results[p.name] for p in self.providers if p.name in results]
        return statuses, metas

    async def _fetch_one(self, provider: Provider, isbn13: str) -> tuple[BookMeta | None, str]:
        try:
            meta = await provider.fetch(self.client, isbn13)
        except httpx.TimeoutException:
            logger.warning("%s : délai dépassé pour %s", provider.name, isbn13)
            return None, "délai dépassé"
        except httpx.HTTPError as exc:
            logger.warning("%s : erreur réseau pour %s (%s)", provider.name, isbn13, exc)
            return None, "injoignable"
        except Exception as exc:  # noqa: BLE001 - un fournisseur cassé ne doit rien bloquer
            logger.exception("%s : réponse inexploitable pour %s (%s)", provider.name, isbn13, exc)
            return None, "réponse inexploitable"
        if meta is None or meta.is_empty():
            return None, "non trouvé"
        return meta, "trouvé"


def clean_genres(genres: list[str]) -> list[str]:
    """Écarte le bruit des vocabulaires OpenLibrary et borne la liste."""
    keep: list[str] = []
    for genre in genres:
        text = genre.strip()
        # « form:manga », « franchise:ONE PIECE »… sont des étiquettes internes.
        if ":" in text or len(text) > 40 or len(text) < 3:
            continue
        keep.append(text)
    return dedupe(keep)[:5]


def _fold(text: str) -> str:
    """Minuscules sans accents : « Eiichirô » et « Eiichiro » désignent le même auteur."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _tokens(title: str) -> set[str]:
    return {token for token in re.split(r"[^\w]+", _fold(title)) if len(token) > 2}


def same_book(reference: BookMeta, other: BookMeta) -> bool:
    """Vrai si deux notices décrivent visiblement le même ouvrage.

    Les ISBN sont parfois réattribués, ou mal saisis dans un catalogue : deux
    sources peuvent alors renvoyer deux livres différents pour le même code.
    Fusionner leurs champs produirait une fiche chimérique (le titre de l'un,
    le résumé de l'autre). Un auteur commun suffit à lever le doute, ce qui
    évite de rejeter « 1984 » face à « Nineteen Eighty-Four ».
    """
    # Les translittérations diffèrent d'un catalogue à l'autre (« Eiichirô Oda »
    # à la BnF, « Eiichiro Oda » au SUDOC) : la comparaison ignore les accents.
    left_authors = {_fold(a) for a in reference.authors}
    right_authors = {_fold(a) for a in other.authors}
    if left_authors & right_authors:
        return True

    left, right = _tokens(reference.title), _tokens(other.title)
    if not left or not right:
        return True
    if left <= right or right <= left:
        return True
    return len(left & right) / len(left | right) >= 0.3


def merge(metas: list[BookMeta], isbn13: str) -> BookMeta:
    """Fusionne les notices : le premier fournisseur qui renseigne un champ gagne."""
    merged = BookMeta(isbn13=isbn13)

    reference = metas[0] if metas else BookMeta()
    rejected = [meta for meta in metas[1:] if not same_book(reference, meta)]
    if rejected:
        logger.info(
            "ISBN %s : notices écartées car différentes de « %s » (%s)",
            isbn13,
            reference.title,
            ", ".join(f"{m.sources[0]}={m.title!r}" for m in rejected if m.sources),
        )
        metas = [meta for meta in metas if meta not in rejected]

    scalar_fields = (
        "title", "subtitle", "publisher", "published_date", "page_count",
        "synopsis", "series", "volume", "language", "country",
        "source_url", "isbn10",
    )
    for field in scalar_fields:
        for meta in metas:
            value = getattr(meta, field)
            if value not in (None, "", []):
                setattr(merged, field, value)
                break

    for meta in metas:
        if meta.authors:
            merged.authors = list(meta.authors)
            break

    # Genre : premier fournisseur renseigné, sans cumul. La forme donnée par les
    # catalogues français (« Mangas », « Romans policiers ») est courte et juste ;
    # la noyer sous les mots-clés d'OpenLibrary la rendrait inutilisable. Les
    # vedettes matière ne servent que si personne ne donne de genre.
    for source in ("genres", "subjects"):
        for meta in metas:
            genres = clean_genres(getattr(meta, source))
            if genres:
                merged.genres = genres
                break
        if merged.genres:
            break

    merged.sources = dedupe([source for meta in metas for source in meta.sources])

    # Les couvertures ont leur propre ordre, décidé par app.covers : la source
    # la mieux fournie passe devant, quelle que soit la hiérarchie des notices.
    merged.cover_candidates = covers.candidates(
        isbn13, [meta.cover_url for meta in metas if meta.cover_url]
    )
    # `cover_url` est la couverture retenue, donc la première de la liste : c'est
    # elle que le formulaire renverra à l'ajout, et elle est déjà en cache.
    merged.cover_url = merged.cover_candidates[0] if merged.cover_candidates else None

    # Un titre du type « One Piece, Tome 12 : ... » livre la série même quand
    # aucun catalogue ne remplit la zone dédiée.
    merged.title, merged.series, merged.volume = series_utils.enrich(
        merged.title, merged.series, merged.volume
    )
    return merged
