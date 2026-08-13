"""Configuration de l'application, entièrement pilotée par variables d'environnement."""

from __future__ import annotations

import json
import os
from functools import lru_cache

DEFAULT_LABELS: dict[str, str] = {
    "isbn": "ISBN",
    "authors": "Auteur",
    "publisher": "Éditeur",
    "published": "Date de parution",
    "pages": "Nombre de pages",
    "genres": "Genre",
    "synopsis": "Synopsis",
    "read": "Lu",
    "series": "Série",
    "volume": "Tome",
    "language": "Langue",
    "source": "Source",
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "oui"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


class Settings:
    """Regroupe toute la configuration lue au démarrage."""

    def __init__(self) -> None:
        # --- Koillection -------------------------------------------------
        self.koillection_url: str = os.environ.get("KOILLECTION_URL", "").rstrip("/")
        self.koillection_username: str = os.environ.get("KOILLECTION_USERNAME", "")
        self.koillection_password: str = os.environ.get("KOILLECTION_PASSWORD", "")
        self.koillection_verify_ssl: bool = _env_bool("KOILLECTION_VERIFY_SSL", True)
        self.default_collection: str = os.environ.get("KOILLECTION_DEFAULT_COLLECTION", "")

        # --- Comportement métier ----------------------------------------
        # Crée (ou réutilise) une sous-collection portant le nom de la série.
        self.series_subcollections: bool = _env_bool("SERIES_SUBCOLLECTIONS", True)
        # Ajoute les genres en tant que tags Koillection en plus du champ texte.
        self.genres_as_tags: bool = _env_bool("GENRES_AS_TAGS", True)
        # Téléverse la couverture trouvée par les fournisseurs.
        self.upload_cover: bool = _env_bool("UPLOAD_COVER", True)
        # Gabarit du nom de l'item quand le livre appartient à une série.
        self.series_item_name: str = os.environ.get(
            "SERIES_ITEM_NAME", "{series} - T{volume:02d} - {title}"
        )

        # --- Fournisseurs de métadonnées --------------------------------
        self.providers: list[str] = _env_list(
            "PROVIDERS",
            ["bnf", "sudoc", "openlibrary", "k10plus", "openbd", "googlebooks"],
        )
        self.provider_timeout: float = _env_float("PROVIDER_TIMEOUT", 8.0)
        # Plafond global : au-delà, on répond avec ce qui est déjà arrivé plutôt
        # que de faire patienter devant une étagère.
        self.lookup_deadline: float = _env_float("LOOKUP_DEADLINE", 4.0)
        self.google_books_key: str = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
        self.isbndb_key: str = os.environ.get("ISBNDB_API_KEY", "")
        self.cache_ttl: int = _env_int("CACHE_TTL", 86400)
        self.cache_size: int = _env_int("CACHE_SIZE", 512)

        # --- Interface / sécurité ---------------------------------------
        self.app_password: str = os.environ.get("APP_PASSWORD", "")
        self.session_secret: str = os.environ.get("SESSION_SECRET", "")
        self.session_days: int = _env_int("SESSION_DAYS", 30)

        # --- Correspondance des champs Koillection ----------------------
        self.labels: dict[str, str] = dict(DEFAULT_LABELS)
        raw_labels = os.environ.get("FIELD_LABELS", "").strip()
        if raw_labels:
            try:
                overrides = json.loads(raw_labels)
            except json.JSONDecodeError as exc:  # pragma: no cover - config utilisateur
                raise ValueError(f"FIELD_LABELS n'est pas un JSON valide : {exc}") from exc
            for key, value in overrides.items():
                if key not in self.labels:
                    raise ValueError(
                        f"FIELD_LABELS : champ inconnu '{key}'. "
                        f"Champs valides : {', '.join(sorted(self.labels))}"
                    )
                self.labels[key] = str(value)

        # Champs volontairement désactivés (valeur vide dans FIELD_LABELS).
        self.labels = {k: v for k, v in self.labels.items() if v}

    @property
    def koillection_configured(self) -> bool:
        return bool(self.koillection_url and self.koillection_username and self.koillection_password)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
