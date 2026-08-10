"""Traduction d'une fiche livre en item Koillection."""

from __future__ import annotations

import json
import logging
import re

import httpx

from . import covers
from .config import Settings
from .history import History
from .koillection import KoillectionClient, KoillectionError
from .models import AddRequest, AddResponse

logger = logging.getLogger(__name__)

#: Ordre d'affichage des champs dans la fiche Koillection.
FIELD_ORDER = (
    "isbn", "authors", "publisher", "published", "pages", "language",
    "series", "volume", "genres", "read", "synopsis", "source",
)


class Importer:
    def __init__(
        self,
        settings: Settings,
        koillection: KoillectionClient,
        history: History,
        http: httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.koillection = koillection
        self.history = history
        self.http = http

    async def add(self, request: AddRequest) -> AddResponse:
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

        # --- doublons -----------------------------------------------------
        if request.isbn13 and not request.force:
            duplicate = await self.koillection.find_duplicate(target, request.isbn13)
            if duplicate is not None:
                return AddResponse(
                    ok=False,
                    duplicate=True,
                    duplicate_of=self.koillection.item_url(duplicate["id"]),
                    collection_title=target.path,
                    message=(
                        f"« {duplicate.get('name')} » possède déjà cet ISBN dans "
                        f"« {target.path} »."
                    ),
                )

        # --- tags ----------------------------------------------------------
        tag_iris: list[str] = []
        if settings.genres_as_tags and request.genres:
            tag_iris = await self.koillection.ensure_tags(request.genres[:5])

        # --- item ----------------------------------------------------------
        name = build_item_name(request, settings.series_item_name)
        item = await self.koillection.create_item(name, target, tag_iris)
        item_id = item["id"]
        item_iri = f"/api/items/{item_id}"

        # --- champs ---------------------------------------------------------
        values = self._build_data(request)
        position = 0
        for key in FIELD_ORDER:
            label = labels.get(key)
            if not label or key not in values:
                continue
            value, datum_type = values[key]
            await self.koillection.add_datum(item_iri, label, value, datum_type, position)
            position += 1

        # --- couverture -------------------------------------------------------
        if settings.upload_cover and request.cover_url:
            cover = await covers.resolve(self.http, [request.cover_url])
            if cover is not None:
                await self.koillection.upload_cover(item_id, cover)

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
            message=f"« {name} » ajouté dans « {target.path} ».",
        )

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
