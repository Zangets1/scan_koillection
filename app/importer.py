"""Traduction d'une fiche livre en item Koillection."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from contextlib import asynccontextmanager

import httpx

from . import covers
from .config import Settings
from .history import History
from .koillection import KoillectionClient, KoillectionError
from .lookup import LookupService
from .models import AddRequest, AddResponse

logger = logging.getLogger(__name__)

#: Ordre d'affichage des champs dans la fiche Koillection.
FIELD_ORDER = (
    "isbn", "authors", "publisher", "published", "pages", "language",
    "series", "volume", "genres", "read", "synopsis", "source",
)


class _OneAtATime:
    """Un verrou par livre.

    Deux validations du même livre — double appui sur « Ajouter », renvoi
    depuis le téléphone après une réponse qui tardait — se déroulaient
    exactement en même temps : chacune cherchait un doublon avant que l'autre
    n'ait créé le sien, et les deux passaient. Elles s'exécutent maintenant
    l'une après l'autre, la seconde voyant l'item de la première. Deux livres
    différents continuent d'être traités en parallèle.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiting: Counter[str] = Counter()

    @asynccontextmanager
    async def __call__(self, key: str):
        lock = self._locks.setdefault(key, asyncio.Lock())
        self._waiting[key] += 1
        try:
            async with lock:
                yield
        finally:
            self._waiting[key] -= 1
            if not self._waiting[key]:
                del self._waiting[key]
                self._locks.pop(key, None)


class Importer:
    def __init__(
        self,
        settings: Settings,
        koillection: KoillectionClient,
        history: History,
        lookup: LookupService,
    ) -> None:
        self.settings = settings
        self.koillection = koillection
        self.history = history
        self.lookup = lookup
        self._one_at_a_time = _OneAtATime()

    async def add(self, request: AddRequest) -> AddResponse:
        name = build_item_name(request, self.settings.series_item_name)
        key = f"{request.collection or ''}|{request.isbn13 or name.casefold()}"
        async with self._one_at_a_time(key):
            return await self._add(request)

    async def _add(self, request: AddRequest) -> AddResponse:
        settings = self.settings
        labels = settings.labels

        root_reference = request.collection or settings.default_collection
        if not root_reference:
            raise KoillectionError(
                "Aucune collection de destination : choisissez-en une ou renseignez "
                "KOILLECTION_DEFAULT_COLLECTION."
            )
        root = await self.koillection.find_collection(root_reference)
        if root is None:
            await self.koillection.collections(refresh=True)
            root = await self.koillection.find_collection(root_reference)
        if root is None:
            raise KoillectionError(f"Collection introuvable dans Koillection : « {root_reference} ».")

        # --- sous-collection de série ------------------------------------
        target = root
        created_collection = False
        series = (request.series or "").strip()
        if series and settings.series_subcollections:
            target, created_collection = await self.koillection.ensure_child_collection(root, series)

        name = build_item_name(request, settings.series_item_name)

        # --- doublons -----------------------------------------------------
        if not request.force:
            duplicate = await self.koillection.find_duplicate(target, request.isbn13, name)
            if duplicate is not None:
                return AddResponse(
                    ok=False,
                    duplicate=True,
                    duplicate_of=self.koillection.item_url(duplicate["id"]),
                    collection_title=target.path,
                    message=(
                        f"« {duplicate.get('name')} » figure déjà dans « {target.path} »."
                    ),
                )
            known = await self._already_recorded(request.isbn13, target.path)
            if known is not None:
                return AddResponse(
                    ok=False,
                    duplicate=True,
                    duplicate_of=self.koillection.item_url(known["item_id"]),
                    collection_title=target.path,
                    message=(
                        f"Cet ISBN a déjà été ajouté le {known['created_at'][:10]} dans "
                        f"« {target.path} », sous le nom « {known['title']} »."
                    ),
                )

        # --- tags ----------------------------------------------------------
        tag_iris: list[str] = []
        if settings.genres_as_tags and request.genres:
            tag_iris = await self.koillection.ensure_tags(request.genres[:5])

        # --- item ----------------------------------------------------------
        item = await self.koillection.create_item(name, target, tag_iris)
        item_id = item["id"]
        item_iri = f"/api/items/{item_id}"

        # --- champs ---------------------------------------------------------
        values = self._build_data(request)
        refused: list[str] = []
        position = 0
        for key in FIELD_ORDER:
            label = labels.get(key)
            if not label or key not in values:
                continue
            value, datum_type = values[key]
            if not await self.koillection.add_datum(item_iri, label, value, datum_type, position):
                refused.append(label)
            position += 1

        # --- couverture -------------------------------------------------------
        # L'item est créé : rien de ce qui suit ne doit plus faire échouer
        # l'ajout, sous peine de laisser une fiche orpheline que l'utilisateur
        # rescannerait — c'est ainsi que naissaient les doublons.
        if settings.upload_cover:
            try:
                cover = await covers.resolve(
                    self.lookup.client, await self._cover_candidates(request)
                )
                if cover is not None:
                    await self.koillection.upload_cover(item_id, cover)
            except (KoillectionError, httpx.HTTPError, OSError) as exc:
                logger.warning("Couverture non téléversée : %s", exc)
                refused.append("couverture")

        await self.history.record(
            {
                "isbn13": request.isbn13,
                "title": request.title,
                "authors": ", ".join(request.authors),
                "series": request.series or "",
                "volume": request.volume,
                "collection": target.path,
                "item_id": item_id,
                "item_url": self.koillection.item_url(item_id),
                "read": request.read,
            }
        )

        return AddResponse(
            ok=True,
            item_id=item_id,
            item_url=self.koillection.item_url(item_id),
            collection_title=target.path,
            created_collection=created_collection,
            warnings=refused,
            message=f"« {name} » ajouté dans « {target.path} ».",
        )

    async def _already_recorded(self, isbn13: str, collection_path: str) -> dict | None:
        """Le filet de sécurité : le même ISBN, déjà envoyé au même endroit.

        La recherche de doublon côté Koillection compare les noms d'items. Elle
        ne voit donc rien quand le titre a changé entre deux scans — une fiche
        corrigée à la main, ou un catalogue qui répond autrement d'un jour à
        l'autre. L'historique local, lui, garde l'ISBN. On vérifie tout de même
        que l'item est toujours en place : un livre supprimé de Koillection doit
        pouvoir être rescanné sans discuter.
        """
        if not isbn13:
            return None
        previous = await self.history.find(isbn13)
        if not previous or not previous.get("item_id"):
            return None
        if (previous.get("collection") or "") != collection_path:
            return None
        if not await self.koillection.item_exists(previous["item_id"]):
            return None
        return previous

    async def _cover_candidates(self, request: AddRequest) -> list[str]:
        """Reprend toute la liste de couvertures trouvée à la recherche.

        La couverture affichée dans l'interface est la première réellement
        valide, qui n'est pas forcément celle du fournisseur prioritaire : la
        BnF répond 500 quand elle n'a pas l'image. Reprendre la liste complète
        évite de téléverser une couverture différente de celle qui a été vue.
        """
        candidates = [request.cover_url] if request.cover_url else []
        if request.isbn13:
            result = await self.lookup.lookup(request.isbn13)
            if result.book:
                candidates.extend(result.book.cover_candidates)
        return [url for url in candidates if url]

    def _build_data(self, request: AddRequest) -> dict[str, tuple[str, str]]:
        """Associe à chaque champ sa valeur et son type Koillection."""
        data: dict[str, tuple[str, str]] = {}

        if request.isbn13:
            data["isbn"] = (request.isbn13, "text")
        if request.authors:
            data["authors"] = (json.dumps(request.authors, ensure_ascii=False), "list")
        if request.publisher:
            data["publisher"] = (request.publisher, "text")
        if request.published_date:
            # Koillection valide strictement le type « date » (AAAA-MM-JJ) alors
            # que la BnF ne donne le plus souvent que l'année : on reste en texte
            # pour que le champ garde le même type d'un livre à l'autre.
            data["published"] = (normalize_date(request.published_date), "text")
        if request.page_count:
            data["pages"] = (str(request.page_count), "number")
        if request.language:
            data["language"] = (request.language, "text")
        if request.series:
            data["series"] = (request.series, "text")
        if request.volume is not None:
            data["volume"] = (str(request.volume), "number")
        if request.genres:
            data["genres"] = (json.dumps(request.genres[:5], ensure_ascii=False), "list")
        # Toujours écrit, y compris à « non lu » : c'est l'information que
        # l'utilisateur veut voir d'un coup d'œil dans Koillection.
        data["read"] = ("1" if request.read else "0", "checkbox")
        if request.synopsis:
            data["synopsis"] = (request.synopsis, "textarea")
        if request.source_url and request.source_url.startswith("https://"):
            # Koillection valide le type « link » : une URL malformée ferait
            # échouer le champ, on ne prend donc que les liens sûrs.
            data["source"] = (request.source_url, "link")
        return data


def build_item_name(request: AddRequest, template: str) -> str:
    """Nom de l'item : « Série - T02 - Titre » ou simplement le titre."""
    title = (request.title or "").strip() or "Sans titre"
    series = (request.series or "").strip()
    if not series or request.volume is None:
        return title
    try:
        return template.format(series=series, volume=request.volume, title=title).strip(" -–—")
    except (KeyError, ValueError, IndexError):
        logger.warning("SERIES_ITEM_NAME invalide, retour au titre simple.")
        return title


def normalize_date(raw: str) -> str:
    """Garde ``AAAA-MM-JJ``/``AAAA-MM`` tels quels, réduit le reste à l'année."""
    text = str(raw).strip()
    if re.fullmatch(r"\d{4}(-\d{2}){0,2}", text):
        return text
    match = re.search(r"(1[0-9]{3}|20[0-9]{2})", text)
    return match.group(1) if match else text
