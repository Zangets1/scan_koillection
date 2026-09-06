"""Client de l'API Koillection (Symfony / API Platform).

Notes d'implémentation :

* l'authentification se fait par jeton JWT obtenu sur ``/api/authentication_token`` ;
* les relations s'expriment en IRI (``/api/collections/<uuid>``) et non en identifiants ;
* les champs personnalisés d'un item sont des « data » créés **après** l'item,
  un par appel ``POST /api/data`` ;
* l'API n'expose aucun filtre de recherche : les collections et les tags sont
  donc listés puis filtrés côté client, avec un cache mémoire.
"""

from __future__ import annotations

import asyncio
import logging
import time
import unicodedata
from urllib.parse import urlparse

import httpx

from .config import Settings
from .covers import Cover
from .models import KoiCollection

logger = logging.getLogger(__name__)

#: Durée de validité du cache des collections et des tags. Assez courte pour
#: qu'une collection créée dans Koillection apparaisse presque aussitôt dans le
#: scanner, assez longue pour ne pas réinterroger l'API à chaque affichage.
CACHE_TTL = 60.0

#: Délai d'observation après un échec d'authentification. L'interface redemande
#: la liste des collections à chaque affichage, et le diagnostic dans la foulée :
#: chacune de ces requêtes réclamait un jeton à un serveur qu'on venait de voir
#: échouer. Le verdict précédent est réutilisé pendant ce délai — l'utilisateur
#: est renseigné aussitôt, et le journal de Koillection cesse de se remplir. Un
#: rafraîchissement demandé explicitement le court-circuite.
AUTH_RETRY_DELAY = 30.0


class KoillectionError(RuntimeError):
    """Erreur fonctionnelle remontée telle quelle à l'interface."""


class KoillectionAuthError(KoillectionError):
    """Jeton JWT non obtenu, avec le code HTTP quand le serveur en a renvoyé un.

    Le code distingue le mot de passe refusé (401) de la panne serveur (5xx) :
    ce ne sont pas les mêmes causes, et surtout pas les mêmes gestes.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class KoillectionClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_at: float = 0.0
        self._auth_error: KoillectionAuthError | None = None
        self._auth_error_at: float = 0.0
        self._lock = asyncio.Lock()
        self._collections: list[KoiCollection] | None = None
        self._collections_at: float = 0.0
        self._tags: dict[str, str] | None = None
        self._tags_at: float = 0.0

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    async def startup(self) -> None:
        if not self.settings.koillection_configured:
            logger.warning(
                "Koillection n'est pas configuré : renseignez KOILLECTION_URL, "
                "KOILLECTION_USERNAME et KOILLECTION_PASSWORD."
            )
            return
        self._client = httpx.AsyncClient(
            base_url=self.settings.koillection_url,
            timeout=httpx.Timeout(30.0),
            verify=self.settings.koillection_verify_ssl,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def configured(self) -> bool:
        return self._client is not None

    def invalidate_cache(self) -> None:
        self._collections = None
        self._tags = None

    def _is_fresh(self, stored_at: float, ttl: float | None = None) -> bool:
        # CACHE_TTL est lu à l'appel, et non figé en valeur par défaut, pour
        # rester ajustable depuis les tests.
        return time.monotonic() - stored_at < (CACHE_TTL if ttl is None else ttl)

    # ------------------------------------------------------------------
    # Diagnostic
    # ------------------------------------------------------------------
    async def diagnose(self) -> list[dict]:
        """Déroule la chaîne de connexion étape par étape.

        « Aucune collection » a quatre causes très différentes — serveur
        injoignable, API d'authentification en panne, identifiants refusés, ou
        compte réellement vide — que l'interface ne savait pas distinguer. Ce
        contrôle nomme la bonne, et interroge toujours le serveur : c'est le
        geste de quelqu'un qui vient de réparer quelque chose.
        """
        steps: list[dict] = []

        def add(label: str, ok: bool, detail: str) -> None:
            steps.append({"label": label, "ok": ok, "detail": detail})

        if not self.settings.koillection_configured:
            manquants = [
                nom
                for nom, valeur in (
                    ("KOILLECTION_URL", self.settings.koillection_url),
                    ("KOILLECTION_USERNAME", self.settings.koillection_username),
                    ("KOILLECTION_PASSWORD", self.settings.koillection_password),
                )
                if not valeur
            ]
            add("Configuration", False, f"Variable(s) non renseignée(s) : {', '.join(manquants)}.")
            return steps
        add("Configuration", True, self.settings.koillection_url)

        assert self._client is not None
        try:
            response = await self._client.get("/api", follow_redirects=True)
            joignable = response.status_code < 500
            add(
                "Koillection joignable",
                joignable,
                f"Réponse HTTP {response.status_code}."
                if joignable
                else f"Le serveur répond {response.status_code}.",
            )
            if not joignable:
                return steps
        except httpx.HTTPError as exc:
            add("Koillection joignable", False, _explain_network_error(exc, self.settings.koillection_url))
            return steps

        try:
            # Éprouver la chaîne, c'est redemander un jeton, pas relire celui
            # qu'on a en poche.
            self._token = None
            await self._ensure_token(force=True)
            add("Identifiants acceptés", True, f"Connecté en tant que « {self.settings.koillection_username} ».")
        except KoillectionError as exc:
            add(_auth_step_label(exc), False, str(exc))
            return steps

        try:
            collections = await self.collections(refresh=True)
        except KoillectionError as exc:
            add("Lecture des collections", False, str(exc))
            return steps

        add(
            "Collections visibles",
            bool(collections),
            f"{len(collections)} collection(s) : {', '.join(c.path for c in collections[:5])}"
            if collections
            else (
                f"Le compte « {self.settings.koillection_username} » n'a aucune collection. "
                f"Créez-la depuis Koillection en étant connecté avec ce compte précis — une "
                f"collection appartient à son créateur et reste invisible aux autres comptes."
            ),
        )
        return steps

    # ------------------------------------------------------------------
    # Requêtes de bas niveau
    # ------------------------------------------------------------------
    async def _authenticate(self) -> str:
        assert self._client is not None
        try:
            response = await self._client.post(
                "/api/authentication_token",
                json={
                    "username": self.settings.koillection_username,
                    "password": self.settings.koillection_password,
                },
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise KoillectionAuthError(
                _explain_network_error(exc, self.settings.koillection_url)
            ) from exc

        if response.status_code in (401, 403):
            raise KoillectionAuthError(
                f"Identifiants Koillection refusés ({response.status_code}). Vérifiez "
                "KOILLECTION_USERNAME et KOILLECTION_PASSWORD ; le nom d'utilisateur "
                "n'est pas l'adresse e-mail.",
                response.status_code,
            )
        if response.status_code >= 400:
            raise KoillectionAuthError(_explain_auth_failure(response), response.status_code)

        try:
            payload = response.json()
        except ValueError:
            payload = None
        token = payload.get("token") if isinstance(payload, dict) else None
        if not token:
            # Un 200 sans jeton, c'est quelqu'un d'autre qui répond : page
            # d'accueil d'un reverse proxy, portail d'authentification…
            raise KoillectionAuthError(
                "Koillection a répondu sans jeton JWT. Un intermédiaire (reverse proxy, "
                "portail d'authentification) répond peut-être à sa place : KOILLECTION_URL "
                "doit désigner Koillection lui-même."
            )
        self._token = token
        self._token_at = time.monotonic()
        return token

    async def _ensure_token(self, force: bool = False) -> str:
        """Renvoie un jeton valide. ``force`` ignore la temporisation d'échec.

        Il ne jette pas pour autant un jeton encore bon : rafraîchir la liste des
        collections ne doit pas coûter une authentification de plus quand tout va
        bien. Qui veut éprouver la chaîne entière — le diagnostic — oublie le
        jeton avant d'appeler.
        """
        async with self._lock:
            if force:
                self._auth_error = None
            elif self._auth_error is not None and self._is_fresh(self._auth_error_at, AUTH_RETRY_DELAY):
                # Le serveur vient d'échouer : on redit pourquoi sans le solliciter.
                raise self._auth_error
            # Les jetons Koillection vivent 1 h ; on renouvelle largement avant.
            if self._token is None or time.monotonic() - self._token_at > 1800:
                try:
                    token = await self._authenticate()
                except KoillectionError as exc:
                    self._auth_error = (
                        exc if isinstance(exc, KoillectionAuthError) else KoillectionAuthError(str(exc))
                    )
                    self._auth_error_at = time.monotonic()
                    raise
                self._auth_error = None
                return token
            return self._token

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | list | None = None,
        params: dict | None = None,
        files: dict | None = None,
        content_type: str = "application/json",
        retry_auth: bool = True,
        force_auth: bool = False,
    ) -> httpx.Response:
        if self._client is None:
            raise KoillectionError(
                "Koillection n'est pas configuré (KOILLECTION_URL / USERNAME / PASSWORD)."
            )
        token = await self._ensure_token(force_auth)
        headers = {"Authorization": f"Bearer {token}"}
        if json_body is not None and files is None:
            headers["Content-Type"] = content_type

        try:
            response = await self._client.request(
                method, path, json=json_body, params=params, files=files, headers=headers
            )
        except httpx.HTTPError as exc:
            raise KoillectionError(f"Koillection injoignable : {exc}") from exc

        if response.status_code == 401 and retry_auth:
            # Jeton périmé : on en redemande un, sans se laisser arrêter par la
            # temporisation, qui ne vise que les pannes.
            self._token = None
            return await self.request(
                method,
                path,
                json_body=json_body,
                params=params,
                files=files,
                content_type=content_type,
                retry_auth=False,
                force_auth=True,
            )
        return response

    async def _get_all(self, path: str, force_auth: bool = False) -> list[dict]:
        """Parcourt toutes les pages d'une collection API Platform."""
        results: list[dict] = []
        page = 1
        while page <= 200:  # garde-fou
            response = await self.request(
                "GET", path, params={"page": page}, force_auth=force_auth and page == 1
            )
            if response.status_code >= 400:
                raise KoillectionError(
                    f"GET {path} a échoué ({response.status_code}) : {response.text[:200]}"
                )
            payload = response.json()
            if isinstance(payload, dict):
                payload = payload.get("hydra:member") or payload.get("member") or []
            if not payload:
                break
            results.extend(payload)
            page += 1
        return results

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------
    async def collections(self, refresh: bool = False) -> list[KoiCollection]:
        if self._collections is not None and not refresh and self._is_fresh(self._collections_at):
            return self._collections

        # Rafraîchir, c'est ce que fait l'utilisateur après avoir réparé quelque
        # chose : la temporisation ne doit pas lui resservir l'erreur d'avant.
        raw = await self._get_all("/api/collections", force_auth=refresh)
        by_id: dict[str, KoiCollection] = {}
        for entry in raw:
            identifier = entry.get("id")
            if not identifier:
                continue
            parent = entry.get("parent")
            by_id[identifier] = KoiCollection(
                id=identifier,
                iri=f"/api/collections/{identifier}",
                title=entry.get("title") or "(sans titre)",
                parent=_iri_id(parent),
            )

        for collection in by_id.values():
            collection.path = _build_path(collection, by_id)

        self._collections = sorted(by_id.values(), key=lambda c: c.path.casefold())
        self._collections_at = time.monotonic()
        return self._collections

    async def find_collection(self, reference: str) -> KoiCollection | None:
        """Retrouve une collection par IRI, identifiant, chemin ou titre."""
        if not reference:
            return None
        wanted = reference.strip()
        identifier = _iri_id(wanted)
        collections = await self.collections()
        for collection in collections:
            if collection.id == identifier:
                return collection
        for collection in collections:
            if collection.path.casefold() == wanted.casefold():
                return collection
        for collection in collections:
            if collection.title.casefold() == wanted.casefold():
                return collection
        return None

    async def create_collection(self, title: str, parent: KoiCollection | None) -> KoiCollection:
        body: dict[str, object] = {"title": title}
        if parent is not None:
            body["parent"] = parent.iri
        response = await self.request("POST", "/api/collections", json_body=body)
        if response.status_code not in (200, 201):
            raise KoillectionError(
                f"Création de la collection « {title} » refusée "
                f"({response.status_code}) : {response.text[:200]}"
            )
        payload = response.json()
        created = KoiCollection(
            id=payload["id"],
            iri=f"/api/collections/{payload['id']}",
            title=payload.get("title") or title,
            parent=parent.id if parent else None,
            path=f"{parent.path} / {title}" if parent else title,
        )
        if self._collections is not None:
            self._collections.append(created)
        return created

    async def ensure_child_collection(
        self, parent: KoiCollection, title: str
    ) -> tuple[KoiCollection, bool]:
        """Retourne la sous-collection ``title`` de ``parent``, en la créant au besoin."""
        collections = await self.collections()
        for collection in collections:
            if collection.parent == parent.id and collection.title.casefold() == title.casefold():
                return collection, False
        # La collection a pu être créée depuis un autre onglet : on rafraîchit
        # avant de risquer un doublon.
        collections = await self.collections(refresh=True)
        for collection in collections:
            if collection.parent == parent.id and collection.title.casefold() == title.casefold():
                return collection, False
        return await self.create_collection(title, parent), True

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------
    async def collection_items(self, collection: KoiCollection) -> list[dict]:
        return await self._get_all(f"/api/collections/{collection.id}/items")

    async def find_duplicate(
        self, collection: KoiCollection, isbn13: str, name: str
    ) -> dict | None:
        """Cherche dans la collection un item qui serait déjà ce livre.

        L'API Koillection n'expose aucun filtre de recherche. Interroger les
        champs de chaque item coûterait une requête par item : sur une
        collection de plusieurs centaines de livres, l'ajout deviendrait
        interminable. On se sert donc du nom — identique quand le même livre est
        scanné deux fois — pour ne vérifier l'ISBN que sur les rares homonymes.

        L'ISBN départage les homonymes, il ne les crée pas : un item du même nom
        **sans** ISBN reste un doublon. C'est même le cas le plus important, car
        un item sans ISBN est presque toujours un ajout précédent dont
        l'écriture des champs a échoué — Koillection qui refuse le champ, ou la
        connexion qui casse au milieu. Le considérer comme un autre livre
        rendait ces ajouts-là définitivement invisibles : chaque nouveau scan
        du même livre en fabriquait une copie de plus, sans le moindre message.
        """
        wanted = _normalize_name(name)
        candidates = [
            item
            for item in await self.collection_items(collection)
            if item.get("id") and _normalize_name(item.get("name", "")) == wanted
        ]
        if not candidates:
            return None

        label = self.settings.labels.get("isbn")
        if not label or not isbn13:
            # Sans champ ISBN configuré, l'homonymie exacte fait office de preuve.
            return candidates[0]

        #: Homonyme dont l'ISBN ne contredit pas celui du livre scanné : gardé
        #: de côté, un ISBN qui concorde vaut mieux et lui passerait devant.
        muet: dict | None = None
        for item in candidates:
            response = await self.request("GET", f"/api/items/{item['id']}/data")
            if response.status_code >= 400:
                # Champs illisibles : on ne peut rien conclure, et devant un
                # homonyme le doute profite à la mise en garde.
                muet = muet or item
                continue
            payload = response.json()
            if isinstance(payload, dict):
                payload = payload.get("hydra:member") or payload.get("member") or []
            inscrits = [
                datum.get("value") for datum in payload if datum.get("label") == label
            ]
            if any(_same_isbn(value, isbn13) for value in inscrits):
                return item
            if not any(_digits(value) for value in inscrits):
                muet = muet or item
        return muet

    async def item_exists(self, item_id: str) -> bool:
        """Dit si un item enregistré dans l'historique est toujours en place."""
        if not item_id:
            return False
        try:
            response = await self.request("GET", f"/api/items/{item_id}")
        except KoillectionError:
            # Koillection muet : on ne peut pas affirmer que l'item existe.
            return False
        return response.status_code < 400

    async def create_item(
        self,
        name: str,
        collection: KoiCollection,
        tags: list[str] | None = None,
    ) -> dict:
        body: dict[str, object] = {
            "name": name,
            "collection": collection.iri,
            "quantity": 1,
        }
        if tags:
            body["tags"] = tags
        response = await self.request("POST", "/api/items", json_body=body)
        if response.status_code not in (200, 201):
            raise KoillectionError(
                f"Création de l'item refusée ({response.status_code}) : {response.text[:300]}"
            )
        return response.json()

    async def add_datum(
        self, item_iri: str, label: str, value: str, datum_type: str, position: int
    ) -> bool:
        """Écrit un champ personnalisé. Renvoie ``False`` si Koillection l'a refusé.

        Un champ refusé (libellé en doublon, valeur invalide, serveur qui
        tousse) ne doit pas faire échouer tout l'ajout : l'item existe déjà.
        Mais il ne doit pas non plus passer inaperçu — c'est ainsi qu'on se
        retrouve avec une fiche sans ISBN, que plus rien ne reconnaîtra ensuite.
        L'appelant reçoit donc le verdict et le remonte à l'utilisateur.
        """
        body = {
            "item": item_iri,
            "type": datum_type,
            "label": label,
            "value": value,
            "position": position,
        }
        try:
            response = await self.request("POST", "/api/data", json_body=body)
        except KoillectionError as exc:
            logger.warning("Champ « %s » non écrit : %s", label, exc)
            return False
        if response.status_code not in (200, 201):
            logger.warning(
                "Champ « %s » refusé par Koillection (%s) : %s",
                label,
                response.status_code,
                response.text[:200],
            )
            return False
        return True

    async def upload_cover(self, item_id: str, cover: Cover) -> bool:
        files = {"file": (f"cover{cover.extension}", cover.content, cover.content_type)}
        response = await self.request("POST", f"/api/items/{item_id}/image", files=files)
        if response.status_code not in (200, 201):
            logger.warning(
                "Téléversement de la couverture refusé (%s) : %s",
                response.status_code,
                response.text[:200],
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------
    async def tags(self, refresh: bool = False) -> dict[str, str]:
        if self._tags is not None and not refresh and self._is_fresh(self._tags_at):
            return self._tags
        raw = await self._get_all("/api/tags", force_auth=refresh)
        self._tags_at = time.monotonic()
        self._tags = {
            (entry.get("label") or "").casefold(): f"/api/tags/{entry['id']}"
            for entry in raw
            if entry.get("id")
        }
        return self._tags

    async def ensure_tags(self, labels: list[str]) -> list[str]:
        known = await self.tags()
        iris: list[str] = []
        for label in labels:
            key = label.casefold()
            if key in known:
                iris.append(known[key])
                continue
            response = await self.request("POST", "/api/tags", json_body={"label": label})
            if response.status_code not in (200, 201):
                logger.warning(
                    "Tag « %s » non créé (%s) : %s", label, response.status_code, response.text[:200]
                )
                continue
            iri = f"/api/tags/{response.json()['id']}"
            known[key] = iri
            iris.append(iri)
        return iris

    def item_url(self, item_id: str) -> str:
        return f"{self.settings.koillection_url}/items/{item_id}"


def _iri_id(value: object) -> str | None:
    """``/api/collections/<uuid>`` → ``<uuid>`` ; laisse passer un uuid nu."""
    if not value:
        return None
    if isinstance(value, dict):
        value = value.get("@id") or value.get("id") or ""
    text = str(value).strip().rstrip("/")
    return text.rsplit("/", 1)[-1] or None


def _build_path(collection: KoiCollection, by_id: dict[str, KoiCollection]) -> str:
    parts = [collection.title]
    seen = {collection.id}
    parent_id = collection.parent
    while parent_id and parent_id in by_id and parent_id not in seen:
        seen.add(parent_id)
        parent = by_id[parent_id]
        parts.append(parent.title)
        parent_id = parent.parent
    return " / ".join(reversed(parts))


def _server_detail(response: httpx.Response) -> str:
    """Extrait le message du serveur : JSON d'API Platform, ou rien.

    Une page d'erreur HTML de Symfony ne dit rien d'utile en quelques centaines
    de caractères ; mieux vaut ne rien citer que de noyer le conseil qui suit.
    """
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        for key in ("detail", "hydra:description", "message", "error_description", "title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())[:200]
    text = (response.text or "").strip()
    if not text or text.startswith("<") or "<html" in text[:200].lower():
        return ""
    return " ".join(text.split())[:200]


def _explain_auth_failure(response: httpx.Response) -> str:
    """Traduit un refus de jeton autre qu'un mot de passe erroné.

    Le message d'avant — « Vérifiez KOILLECTION_URL » — était le pire conseil
    possible sur une erreur 500 : l'adresse est justement celle qui vient de
    répondre 200 à l'étape précédente du diagnostic. On envoyait l'utilisateur
    retourner sa configuration pendant que la panne était chez Koillection.
    """
    code = response.status_code
    detail = _server_detail(response)
    # Le message du serveur garde sa ponctuation : rien ne s'ajoute après le guillemet.
    cite = f" Koillection dit : « {detail} »" if detail else ""

    if code == 404:
        return (
            f"Koillection ne connaît pas /api/authentication_token (404). KOILLECTION_URL "
            f"ne désigne pas la racine d'un Koillection, ou un reverse proxy n'en publie "
            f"qu'une partie.{cite}"
        )
    if code in (502, 503, 504):
        return (
            f"Un intermédiaire répond {code} à la place de Koillection : le conteneur "
            f"redémarre, ou le reverse proxy ne le joint plus. Réessayez une fois "
            f"Koillection reparti.{cite}"
        )
    if code >= 500:
        return (
            f"Koillection répond, mais son API d'authentification échoue ({code}) : "
            f"l'adresse n'est donc pas en cause. La cause habituelle est la paire de clés "
            f"JWT (config/jwt/private.pem et public.pem) absente, illisible par le serveur "
            f"web, ou générée avec une autre passphrase. Régénérez-la depuis le conteneur "
            f"Koillection — « php bin/console lexik:jwt:generate-keypair --overwrite » — "
            f"puis redémarrez-le. Son journal donne le message exact.{cite}"
        )
    return f"Authentification Koillection impossible ({code}).{cite}"


def _auth_step_label(exc: Exception) -> str:
    """Nomme l'étape de diagnostic d'après ce qui a réellement échoué.

    Afficher « Identifiants acceptés ✗ » sur une erreur 500 envoyait réinitialiser
    un mot de passe qui n'y était pour rien : le serveur ne l'a même pas regardé.
    """
    status = getattr(exc, "status", None)
    if status is not None and status >= 500:
        return "API d'authentification"
    return "Identifiants acceptés"


#: Formulations d'échec de résolution DNS selon la plateforme.
_DNS_ERRORS = ("name or service not known", "nodename nor servname", "getaddrinfo failed", "no address")


def _explain_network_error(exc: Exception, url: str) -> str:
    """Traduit une erreur réseau en cause probable, plutôt qu'en trace technique."""
    message = str(exc).lower()
    host = urlparse(url).hostname or url

    if any(marque in message for marque in _DNS_ERRORS):
        return (
            f"Le nom « {host} » est introuvable. S'il s'agit d'un autre conteneur, les deux "
            f"ne partagent pas le même réseau Docker : chaque pile Compose crée le sien. "
            f"Rattachez-les (voir les lignes « networks » du docker-compose.yml) ou "
            f"utilisez l'adresse IP du NAS et le port publié par Koillection."
        )
    if "connection refused" in message or "all connection attempts failed" in message:
        return (
            f"Rien ne répond sur {url}. Vérifiez le port — celui de Koillection, pas celui "
            f"du scanner — et notez que « localhost » désigne, depuis le conteneur, le "
            f"conteneur lui-même et non le NAS."
        )
    if "timed out" in message or isinstance(exc, httpx.TimeoutException):
        return f"{url} ne répond pas dans le délai imparti. Pare-feu ou serveur surchargé ?"
    return f"{exc.__class__.__name__} : {exc}"


def _normalize_name(value: str) -> str:
    """Compare les noms d'items en ignorant casse, accents et ponctuation."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in without_accents.casefold() if c.isalnum())


def _digits(value: object) -> str:
    """Réduit un ISBN à ses caractères significatifs : « 978-2-07 » → « 978207 »."""
    return "".join(c for c in str(value or "") if c.isalnum()).upper()


def _same_isbn(left: object, right: str) -> bool:
    return bool(_digits(left)) and _digits(left) == _digits(right)
