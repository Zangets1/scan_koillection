"""Modèles de données partagés entre les fournisseurs, l'API et le front."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BookMeta(BaseModel):
    """Métadonnées d'un livre, normalisées quelle que soit la source."""

    isbn13: str = ""
    isbn10: str | None = None
    title: str = ""
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    #: ``YYYY``, ``YYYY-MM`` ou ``YYYY-MM-DD``
    published_date: str | None = None
    page_count: int | None = None
    #: Genre au sens « forme » : Romans, Bandes dessinées, Mangas…
    genres: list[str] = Field(default_factory=list)
    #: Indexation matière, nettement plus bruitée. Sert de repli quand aucune
    #: source ne donne de genre : « Littérature bas-allemande » vaut mieux que rien,
    #: mais ne doit jamais l'emporter sur « Mangas ».
    subjects: list[str] = Field(default_factory=list)
    synopsis: str | None = None
    series: str | None = None
    volume: int | None = None
    language: str | None = None
    cover_url: str | None = None
    #: Toutes les couvertures proposées, dans l'ordre de préférence. Les
    #: catalogues répondent souvent 200 avec une image vide : la validation est
    #: faite à la demande par :mod:`app.covers`.
    cover_candidates: list[str] = Field(default_factory=list)
    #: Lien vers la notice d'origine (BnF, OpenLibrary…)
    source_url: str | None = None
    #: Fournisseurs ayant contribué, dans l'ordre de priorité
    sources: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.title or self.authors)


class LookupResponse(BaseModel):
    found: bool
    isbn13: str
    book: BookMeta | None = None
    #: Résultat brut de chaque fournisseur, pour diagnostic dans l'UI
    providers: dict[str, str] = Field(default_factory=dict)
    elapsed_ms: int = 0
    message: str | None = None


class AddRequest(BaseModel):
    """Ce que le formulaire renvoie au moment de l'ajout dans Koillection."""

    isbn13: str = ""
    title: str
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    published_date: str | None = None
    page_count: int | None = None
    genres: list[str] = Field(default_factory=list)
    synopsis: str | None = None
    series: str | None = None
    volume: int | None = None
    language: str | None = None
    cover_url: str | None = None
    #: Lien vers la notice d'origine, enregistré comme champ « Source »
    source_url: str | None = None
    read: bool = False
    #: IRI (``/api/collections/<uuid>``) ou identifiant de la collection racine
    collection: str | None = None
    #: Force l'ajout même si un item avec le même ISBN existe déjà
    force: bool = False


class AddResponse(BaseModel):
    ok: bool
    item_id: str | None = None
    item_url: str | None = None
    collection_title: str | None = None
    created_collection: bool = False
    duplicate: bool = False
    duplicate_of: str | None = None
    message: str | None = None


class KoiCollection(BaseModel):
    id: str
    iri: str
    title: str
    parent: str | None = None
    path: str = ""
