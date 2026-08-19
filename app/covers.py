"""Résolution des couvertures.

Les couvertures ne sont pas des métadonnées : elles ne viennent pas des mêmes
services, et la meilleure source de notices n'est pas la meilleure source
d'images. Le SUDOC, K10plus et la Library of Congress n'en publient aucune, la
BnF ne met en ligne qu'une partie de ses vignettes et répond 500 avec une page
HTML pour le reste, OpenLibrary sert un GIF transparent de 43 octets sur
l'essentiel de l'édition française. Tant que la couverture n'était qu'un
sous-produit des catalogues interrogés, elle manquait donc presque toujours.

D'où ce module : les sources d'images ont leur propre liste, leur propre ordre,
et la première qui rend une image exploitable l'emporte. Mesuré sur 46 ISBN
depuis le serveur du projet — voir ``tools/mesure-couvertures.py`` :

============  ===============  ==============  ===============
source        livres français  livres anglais  temps médian
============  ===============  ==============  ===============
ePagine       96 %             33 %            65 à 96 ms
OpenLibrary   17 %             77 %            1,0 à 3,1 s
BnF           14 %             —               59 ms
============  ===============  ==============  ===============

Aucun service ne dit franchement « je n'ai pas l'image » : la BnF répond 500 en
HTML, OpenLibrary un GIF vide, ePagine et Google une image « couverture
indisponible » parfaitement valide — celle de Google à ``zoom=3`` pèse 246 ko,
aucun seuil de taille ne la distingue d'une vraie couverture. Chaque candidat
est donc réellement téléchargé et vérifié avant d'être affiché ou téléversé
dans Koillection.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from urllib.parse import urlparse

import httpx

from .providers.base import dedupe

logger = logging.getLogger(__name__)

#: En dessous, il s'agit d'un pixel de remplissage et non d'une couverture.
MIN_COVER_BYTES = 2000
MAX_COVER_BYTES = 8 * 1024 * 1024

#: L'URL de couverture transite par le navigateur : sans liste blanche, le
#: service deviendrait un relais HTTP ouvert vers le réseau interne du NAS.
ALLOWED_HOSTS = {
    "catalogue.bnf.fr",
    "covers.openlibrary.org",
    "images.epagine.fr",
    "openbd.jp",
    "cover.openbd.jp",
    "books.google.com",
    "books.googleusercontent.com",
    "images.isbndb.com",
}

#: Empreintes MD5 des images « couverture indisponible », relevées le 19 août
#: 2026. Elles passent toutes les autres vérifications : bon code, bon type,
#: taille honnête. Ce qui les trahit, c'est d'être identiques d'un livre à
#: l'autre — ``tools/mesure-couvertures.py`` démasque celles qui apparaîtraient
#: plus tard, en repérant une même empreinte servie pour deux ISBN.
PLACEHOLDERS = {
    "5da5beba0e74818b1dee869cb519d37d": "ePagine",
    "d7c21c65fc861fc5128753e9e091b23c": "Google Books (zoom=1)",
    "a64fa89d7ebc97075c1d363fc5fea71f": "Google Books (zoom=0 et 2)",
    "1fe98bd081e1f98c8193d52c74cf2ad2": "Google Books (zoom=3)",
}


def epagine_url(isbn13: str) -> str | None:
    """Couverture du réseau des librairies indépendantes, déduite de l'EAN.

    C'est la source la mieux fournie et la plus rapide des trois mesurées, et
    elle ne coûte ni clé d'API ni recherche préalable : le chemin se construit
    à partir des trois derniers chiffres de l'EAN, une seule requête suffit.

    Seul ce suffixe existe : ``_1_100``, ``_1_300``, ``_1_600`` et la variante
    ``.webp`` renvoient tous la même image « couverture indisponible » de
    2 687 octets, écartée par :data:`PLACEHOLDERS`.

    Ce n'est pas une API publique documentée : le motif d'URL peut changer ou
    être fermé. C'est pourquoi il reste un candidat parmi d'autres — s'il
    disparaît, la BnF et OpenLibrary reprennent la main comme avant, sans que
    rien ne casse. Le projet en fait par ailleurs un usage mesuré : une requête
    par livre scanné, et l'image est ensuite stockée dans Koillection, jamais
    rechargée depuis le service.
    """
    if len(isbn13) != 13 or not isbn13.isdigit():
        return None
    return f"https://images.epagine.fr/{isbn13[-3:]}/{isbn13}_1_75.jpg"


def candidates(isbn13: str, from_catalogues: list[str]) -> list[str]:
    """Couvertures à essayer pour cet ISBN, dans l'ordre.

    L'ordre n'est pas celui des catalogues. Pour les notices, la BnF fait
    autorité et les autres ne comblent que les vides ; pour les images, la
    question n'est pas qui fait autorité mais qui détient le fichier, et à
    quelle vitesse. ePagine passe donc devant : elle répond plus souvent et dix
    à trente fois plus vite, si bien que la boucle de :func:`resolve` s'arrête
    au premier candidat dans la plupart des cas — la couverture s'affiche plus
    tôt qu'avant, alors même que la liste s'est allongée.

    OpenLibrary ferme la marche par une URL construite depuis l'ISBN : elle
    aboutit parfois là où le catalogue lui-même n'a rien renvoyé.
    """
    urls = []
    epagine = epagine_url(isbn13)
    if epagine:
        urls.append(epagine)
    urls.extend(from_catalogues)
    urls.append(f"https://covers.openlibrary.org/b/isbn/{isbn13}-L.jpg")
    return dedupe([url for url in urls if url])


def is_allowed(url: str) -> bool:
    """Vrai si l'URL pointe vers un service de couverture connu."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in ALLOWED_HOSTS or any(host.endswith(f".{h}") for h in ALLOWED_HOSTS)


class Cover:
    def __init__(self, content: bytes, content_type: str, url: str) -> None:
        self.content = content
        self.content_type = content_type
        self.url = url

    @property
    def extension(self) -> str:
        return {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/avif": ".avif",
        }.get(self.content_type, ".jpg")


class _ImageCache:
    """Garde quelques couvertures en mémoire, le temps d'un ajout.

    La même image est résolue deux fois : une fois pour l'afficher dans la
    fiche, une seconde quelques secondes plus tard quand l'utilisateur valide
    l'ajout. Sans ce cache, elle traverse le réseau deux fois et l'attente
    devant l'étagère double sans rien apporter.

    Volontairement minuscule — quelques livres, dix minutes, et rien de plus
    lourd que 2 Mio — parce qu'il vit dans la mémoire d'un conteneur de NAS et
    qu'il ne sert qu'à couvrir l'intervalle entre l'affichage et l'ajout.
    """

    def __init__(self, maxsize: int = 8, ttl: int = 600, max_bytes: int = 2 * 1024 * 1024) -> None:
        self.maxsize = maxsize
        self.ttl = ttl
        self.max_bytes = max_bytes
        self._store: OrderedDict[str, tuple[float, Cover]] = OrderedDict()

    def get(self, url: str) -> Cover | None:
        entry = self._store.get(url)
        if entry is None:
            return None
        stored_at, cover = entry
        if time.monotonic() - stored_at > self.ttl:
            self._store.pop(url, None)
            return None
        self._store.move_to_end(url)
        return cover

    def set(self, url: str, cover: Cover) -> None:
        if len(cover.content) > self.max_bytes:
            return
        self._store[url] = (time.monotonic(), cover)
        self._store.move_to_end(url)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


_CACHE = _ImageCache()


def clear_cache() -> None:
    """Vide le cache d'images (les tests en ont besoin, l'application non)."""
    _CACHE.clear()


async def resolve(client: httpx.AsyncClient, candidate_urls: list[str]) -> Cover | None:
    """Renvoie la première couverture réellement exploitable."""
    for url in candidate_urls:
        if not url or not is_allowed(url):
            continue
        cached = _CACHE.get(url)
        if cached is not None:
            return cached
        try:
            response = await client.get(url, timeout=10.0)
        except httpx.HTTPError as exc:
            logger.info("Couverture injoignable (%s) : %s", url, exc)
            continue
        if response.status_code != 200:
            continue
        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            continue
        content = response.content
        if not MIN_COVER_BYTES <= len(content) <= MAX_COVER_BYTES:
            continue
        if content_type == "image/gif":
            # OpenLibrary sert un GIF transparent en guise de « pas de couverture ».
            continue
        service = PLACEHOLDERS.get(hashlib.md5(content).hexdigest())
        if service is not None:
            logger.info("Couverture de remplacement écartée (%s) : %s", service, url)
            continue
        cover = Cover(content, content_type, url)
        _CACHE.set(url, cover)
        return cover
    return None
