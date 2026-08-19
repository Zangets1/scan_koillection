#!/usr/bin/env python3
"""Quelle source détient réellement la couverture d'un livre ?

Le projet ne cherche pas les couvertures : il ramasse celles que les catalogues
de notices laissent au passage. Or trois des cinq fournisseurs par défaut — le
SUDOC, K10plus, la Library of Congress — n'ont aucune image, la BnF ne publie
sa vignette que pour une partie du dépôt légal, et OpenLibrary sert un GIF vide
de 43 octets pour l'essentiel de l'édition française. D'où des fiches sans
couverture, et la question que pose ce script : pour chaque livre, laquelle des
sources d'images connues détient vraiment l'image, en combien de temps, et à
quelle taille.

Il reprend les règles de validation de `app/covers.py` — 200, `image/*`, entre
2 ko et 8 Mio, pas de GIF — et y ajoute les deux pièges qu'elles ne voient pas :

  · **L'image de remplacement.** « Image non disponible » est une vraie image,
    servie en 200 avec un type `image/jpeg` parfaitement honnête. Celle d'ePagine
    pèse 2,7 ko, celle de Google 10,8 ko, et à `zoom=3` Google en sert une de
    246 ko : aucun seuil de taille ne les distingue d'une couverture. On les
    reconnaît autrement — elles sont identiques d'un livre à l'autre. Une même
    empreinte servie pour deux ISBN différents n'est pas une couverture.

  · **La vignette.** Google sans clé répond pour près de huit livres anglophones
    sur dix — en 128 pixels de large, ce qui donne une bouillie dans Koillection.
    Comme pour la Library of Congress, qu'une source réponde ne dit rien de ce
    qu'elle apporte : il faut regarder la largeur.

    python3 mesure-couvertures.py            # les livres de votre historique
    python3 mesure-couvertures.py 20         # les 20 premiers, pour aller vite
    python3 mesure-couvertures.py --corpus   # le corpus embarqué, si pas d'historique

Le corpus par défaut, ce sont **vos** livres : le script lit les ISBN déjà
ajoutés dans `data/history.sqlite3`. C'est la seule mesure qui vaille — la
couverture d'un catalogue dépend de ce qu'on lui demande, et un banc d'essai
générique ne dit rien de votre étagère. À défaut d'historique, il retombe sur un
corpus embarqué de 46 ISBN réels.

À lancer DEPUIS LA MACHINE qui fera les requêtes : ces images viennent de
réseaux de diffusion qui filtrent parfois par adresse ou par pays, et c'est
invérifiable ailleurs. Le script ne modifie rien, ni Koillection ni le dépôt.

Sans aucune dépendance : urllib, sqlite3, hashlib et struct de la bibliothèque
standard, rien à installer.
"""
import hashlib
import json
import sqlite3
import statistics
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

# Ne jamais imposer un encodage à la console : forcer l'UTF-8 sur une console
# Windows en cp1252 produit du « rÃ©pond » là où l'on voulait « répond ».
if hasattr(sys.stdout, "reconfigure"):  # Python 3.7+
    sys.stdout.reconfigure(errors="replace")

UA = "scan-koillection/2.0 (+https://github.com/zangets1/scan_koillection) mesure ponctuelle"
MXC = "{info:lc/xmlns/marcxchange-v2}"

#: Règles de app/covers.py, reprises telles quelles pour mesurer ce que le
#: projet accepterait réellement.
TAILLE_MINIMALE = 2000
TAILLE_MAXIMALE = 8 * 1024 * 1024

#: En dessous, c'est une vignette de liste de résultats, pas une couverture :
#: Koillection l'affiche autour de 300 px et l'étirement se voit.
LARGEUR_MINIMALE = 250

#: Empreintes relevées le 19 août 2026. La détection ne repose pas sur cette
#: table — une même image servie pour deux ISBN est démasquée toute seule — mais
#: elle permet de reconnaître un remplacement dès le premier livre du corpus.
REMPLACEMENTS = {
    "d7c21c65fc861fc5128753e9e091b23c": "Google, « image non disponible » (zoom=1)",
    "a64fa89d7ebc97075c1d363fc5fea71f": "Google, « image non disponible » (zoom=0 et 2)",
    "1fe98bd081e1f98c8193d52c74cf2ad2": "Google, « image non disponible » (zoom=3)",
    "5da5beba0e74818b1dee869cb519d37d": "ePagine, « couverture indisponible »",
}

#: 28 ISBN francophones et 18 anglophones tirés de notices réelles. Ce corpus ne
#: sert que si l'historique est vide : il donne un ordre de grandeur, pas une
#: réponse sur votre collection.
CORPUS = [
    # Bandes dessinées et albums français
    "9782203015326", "9782203985766", "9782203161986", "9782203110069",
    "9782205206265", "9782205044010", "9782756081991", "9782756098814",
    "9782756097442", "9782756097190", "9782723440516", "9782723446013",
    "9782723455084", "9782723450010",
    # Poche et jeunesse
    "9782266262439", "9782266262446", "9782266254533", "9782266283427",
    # Guides et beaux livres récents
    "9782344058190", "9782344056813", "9782344046104", "9782344056011",
    "9782344057445",
    # Mangas récents
    "9782380713954", "9782380714197", "9782380712940", "9782380713282",
    "9782380712773",
    # Anglophones
    "9780571212682", "9781408883358", "9780141341569", "9780345339683",
    "9781526650863", "9780735281264", "9780865479593", "9780141186917",
    "9781423163008", "9780575091504", "9781250238429", "9781338126198",
    "9780836218220", "9780345519474", "9781797127972", "9780385354288",
    "9781529059960", "9780765380722",
]

#: Emplacements habituels de l'historique : le dossier monté du conteneur, la
#: pile d'essai v2, puis le chemin interne pour un lancement dans le conteneur.
HISTORIQUES = ("data/history.sqlite3", "data-v2/history.sqlite3", "/data/history.sqlite3")


# ----------------------------------------------------------------------
# Réseau
# ----------------------------------------------------------------------
class Reponse:
    def __init__(self, code: int, type_mime: str, corps: bytes, ms: int) -> None:
        self.code = code
        self.type_mime = type_mime
        self.corps = corps
        self.ms = ms
        self.empreinte = hashlib.md5(corps).hexdigest() if corps else ""


def telecharger(url: str, timeout: int = 20) -> Reponse:
    """Récupère une URL sans jamais lever : un échec est une mesure comme une autre.

    La BnF répond 500 avec une page HTML quand elle n'a pas la vignette, ce qui
    passe par `HTTPError` : le corps est lu quand même, c'est lui qui dit qu'il
    s'agit de `text/html` et non d'une image.
    """
    requete = urllib.request.Request(url, headers={"User-Agent": UA})
    debut = time.perf_counter()
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            corps = reponse.read(TAILLE_MAXIMALE + 1)
            type_mime = (reponse.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            code = reponse.status
    except urllib.error.HTTPError as erreur:
        corps = erreur.read(TAILLE_MAXIMALE + 1) if erreur.fp else b""
        type_mime = (erreur.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        code = erreur.code
    except (urllib.error.URLError, OSError, ValueError):
        return Reponse(0, "", b"", int((time.perf_counter() - debut) * 1000))
    return Reponse(code, type_mime, corps, int((time.perf_counter() - debut) * 1000))


def texte(url: str, timeout: int = 20) -> str | None:
    reponse = telecharger(url, timeout)
    return reponse.corps.decode("utf-8", "replace") if reponse.code == 200 else None


# ----------------------------------------------------------------------
# Lecture d'image, réduite à ce qui décide : la largeur
# ----------------------------------------------------------------------
def largeur(corps: bytes) -> int:
    """Largeur en pixels, lue dans l'en-tête. 0 si le format n'est pas reconnu.

    Aucune dépendance : trois formats suffisent, ce sont les seuls que ces
    services servent.
    """
    if corps[:2] == b"\xff\xd8":  # JPEG : parcours des segments jusqu'au SOF
        index = 2
        while index < len(corps) - 9:
            if corps[index] != 0xFF:
                index += 1
                continue
            marqueur = corps[index + 1]
            if marqueur in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return struct.unpack(">H", corps[index + 7:index + 9])[0]
            if marqueur in (0xD8, 0xD9) or 0xD0 <= marqueur <= 0xD7:
                index += 2
                continue
            index += 2 + struct.unpack(">H", corps[index + 2:index + 4])[0]
        return 0
    if corps[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">I", corps[16:20])[0]
    if corps[:4] == b"RIFF" and corps[8:12] == b"WEBP":
        if corps[12:16] == b"VP8 ":
            return struct.unpack("<H", corps[26:28])[0] & 0x3FFF
        if corps[12:16] == b"VP8L":
            return (struct.unpack("<I", corps[21:25])[0] & 0x3FFF) + 1
        if corps[12:16] == b"VP8X":
            return int.from_bytes(corps[24:27], "little") + 1
    return 0


# ----------------------------------------------------------------------
# ISBN
# ----------------------------------------------------------------------
def isbn10(isbn13: str) -> str | None:
    """« 9782070368228 » -> « 2070368220 ». Certains services n'indexent que cette forme."""
    if len(isbn13) != 13 or not isbn13.startswith("978") or not isbn13.isdigit():
        return None
    corps = isbn13[3:12]
    total = sum((10 - i) * int(c) for i, c in enumerate(corps))
    cle = (11 - total % 11) % 11
    return corps + ("X" if cle == 10 else str(cle))


def aire(isbn13: str) -> str:
    """Aire linguistique de l'éditeur, comme `app.isbn.registration_group`."""
    # Préfixes longs d'abord, comme dans app/isbn.py : « 978-84 » doit primer
    # sur un éventuel « 978-8 ».
    for prefixe, groupe in (("97910", "fr"), ("97884", "es"), ("97888", "it"),
                            ("9798", "en"), ("9780", "en"), ("9781", "en"),
                            ("9782", "fr"), ("9783", "de"), ("9784", "ja")):
        if isbn13.startswith(prefixe):
            return groupe
    return "autre"


# ----------------------------------------------------------------------
# Les sources d'images
# ----------------------------------------------------------------------
def url_epagine(isbn: str) -> list[str]:
    """CDN du réseau des librairies indépendantes, indexé par EAN.

    Seul ce suffixe existe : `_1_100`, `_1_300`, `_1_600` et la variante `.webp`
    renvoient tous le même PNG de remplacement de 2 687 octets.
    """
    return [f"https://images.epagine.fr/{isbn[-3:]}/{isbn}_1_75.jpg"]


def url_openlibrary(isbn: str) -> list[str]:
    """Les deux formes de l'ISBN : une notice ancienne n'est indexée qu'en dix chiffres."""
    urls = [f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"]
    court = isbn10(isbn)
    if court:
        urls.append(f"https://covers.openlibrary.org/b/isbn/{court}-L.jpg")
    return urls


def url_google(zoom: int):
    def fabrique(isbn: str) -> list[str]:
        # `books/content` ne consomme pas le quota de l'API JSON : le « quota
        # dépassé » qui a fait sortir Google Books des catalogues interrogés ne
        # concerne pas cette adresse. Le niveau de zoom change tout : zoom=1
        # donne 128 px pour beaucoup de livres, zoom=3 donne 575 px pour bien
        # moins. C'est exactement ce que cette mesure doit trancher.
        return [f"https://books.google.com/books/content?vid=ISBN{isbn}"
                f"&printsec=frontcover&img=1&zoom={zoom}"]
    return fabrique


def url_bnf(isbn: str) -> list[str]:
    """La vignette BnF est indexée par ark, qu'il faut demander au SRU.

    Cette requête n'est pas comptée dans le temps mesuré : l'application, elle,
    tient déjà l'ark de la notice qu'elle vient de lire, la vignette ne lui coûte
    que le téléchargement de l'image.
    """
    params = urllib.parse.urlencode({
        "version": "1.2", "operation": "searchRetrieve",
        "query": f'bib.fuzzyISBN any "{isbn}"',
        "recordSchema": "unimarcXchange", "maximumRecords": "1"})
    corps = texte(f"https://catalogue.bnf.fr/api/SRU?{params}")
    if not corps:
        return []
    try:
        racine = ET.fromstring(corps)
    except ET.ParseError:
        return []
    for notice in racine.iter(f"{MXC}record"):
        ark = notice.get("id") or ""
        if ark.startswith("ark:"):
            return [f"https://catalogue.bnf.fr/couverture?&appName=NE&idArk={ark}&couverture=1"]
    return []


def url_openbd(isbn: str) -> list[str]:
    """openBD donne l'URL de la couverture dans la notice elle-même."""
    corps = texte(f"https://api.openbd.jp/v1/get?isbn={isbn}")
    if not corps:
        return []
    try:
        notices = json.loads(corps)
    except ValueError:
        return []
    if not notices or not notices[0]:
        return []
    couverture = ((notices[0].get("summary") or {}).get("cover") or "").strip()
    return [couverture] if couverture else []


#: nom, aires concernées (None = toutes), fabrique d'URL candidates.
SOURCES = (
    ("ePagine", None, url_epagine),
    ("BnF", {"fr"}, url_bnf),
    ("OpenLibrary", None, url_openlibrary),
    ("Google zoom=3", None, url_google(3)),
    ("Google zoom=1", None, url_google(1)),
    ("openBD", {"ja"}, url_openbd),
)

#: Livres dont on sait qu'une couverture existe chez chaque source. Si un témoin
#: échoue ici alors qu'il passe ailleurs, c'est la machine qui est filtrée, pas
#: la source qui est vide — sans ce garde-fou, la mesure conclurait « apport nul »
#: à une question jamais posée.
TEMOINS = {
    "ePagine": "9782344058190",
    "BnF": "9782266262439",
    "OpenLibrary": "9780571212682",
    "Google zoom=3": "9781408883358",
    "Google zoom=1": "9781408883358",
}


# ----------------------------------------------------------------------
# Mesure
# ----------------------------------------------------------------------
class Trouvaille:
    """Ce qu'une source a rendu pour un livre."""

    def __init__(self, verdict: str, largeur_px: int = 0, ms: int = 0, empreinte: str = "") -> None:
        self.verdict = verdict          # "couverture", "vignette", "remplacement", "rien"
        self.largeur = largeur_px
        self.ms = ms
        self.empreinte = empreinte

    @property
    def utilisable(self) -> bool:
        return self.verdict == "couverture"


def interroger(fabrique, isbn: str) -> Trouvaille:
    """Essaie les URL d'une source et retient la première image plausible."""
    try:
        urls = fabrique(isbn)
    except Exception:  # noqa: BLE001 - une source cassée ne doit pas arrêter la mesure
        return Trouvaille("rien")

    total_ms = 0
    for url in urls:
        reponse = telecharger(url)
        total_ms += reponse.ms
        if reponse.code != 200 or not reponse.type_mime.startswith("image/"):
            continue
        if reponse.type_mime == "image/gif":
            continue  # OpenLibrary sert un GIF transparent en guise de « rien »
        if not TAILLE_MINIMALE <= len(reponse.corps) <= TAILLE_MAXIMALE:
            continue
        px = largeur(reponse.corps)
        if reponse.empreinte in REMPLACEMENTS:
            verdict = "remplacement"
        else:
            verdict = "couverture" if px >= LARGEUR_MINIMALE else "vignette"
        return Trouvaille(verdict, px, total_ms, reponse.empreinte)
    return Trouvaille("rien", 0, total_ms)


def demasquer_remplacements(mesures: dict) -> set[str]:
    """Empreintes servies pour plus d'un livre : ce sont des images de remplacement.

    Deux rééditions partageant une illustration peuvent être signalées à tort ;
    c'est sans conséquence sur le verdict, qui se joue à plusieurs dizaines de
    livres d'écart, et les empreintes sont affichées pour vérification.
    """
    porteurs: dict[str, set[str]] = {}
    for isbn, trouvailles in mesures.items():
        for trouvaille in trouvailles.values():
            if trouvaille.empreinte:
                porteurs.setdefault(trouvaille.empreinte, set()).add(isbn)
    return {e for e, isbns in porteurs.items() if len(isbns) > 1} | set(REMPLACEMENTS)


# ----------------------------------------------------------------------
# Corpus
# ----------------------------------------------------------------------
def lire_historique() -> tuple[list[str], str]:
    """ISBN déjà ajoutés par le projet, du plus récent au plus ancien."""
    for chemin in HISTORIQUES:
        fichier = Path(chemin)
        if not fichier.is_file():
            continue
        try:
            with sqlite3.connect(f"file:{fichier}?mode=ro", uri=True) as connexion:
                lignes = connexion.execute(
                    "SELECT isbn13 FROM additions ORDER BY id DESC").fetchall()
        except sqlite3.Error:
            continue
        vus, isbns = set(), []
        for (isbn,) in lignes:
            if isbn and isbn not in vus:
                vus.add(isbn)
                isbns.append(isbn)
        if isbns:
            return isbns, str(fichier)
    return [], ""


def pluriel(nombre: int, mot: str = "livre") -> str:
    """« 1 livre », « 3 livres » : un rapport qui se relit sans buter."""
    return f"{nombre} {mot}{'s' if nombre > 1 else ''}"


# ----------------------------------------------------------------------
# Rapport
# ----------------------------------------------------------------------
def tableau_par_aire(corpus: list[str], mesures: dict, faux: set[str]) -> None:
    for zone in sorted({aire(i) for i in corpus}):
        livres = [i for i in corpus if aire(i) == zone]
        print(f"\n   aire « {zone} » — {pluriel(len(livres))}")
        print(f"      {'source':<16}{'couverture':>12}{'vignette':>10}"
              f"{'remplac.':>10}{'rien':>7}{'largeur':>9}{'temps':>9}")
        for nom, aires, _ in SOURCES:
            if aires is not None and zone not in aires:
                continue
            comptes = {"couverture": 0, "vignette": 0, "remplacement": 0, "rien": 0}
            largeurs, temps = [], []
            for isbn in livres:
                trouvaille = mesures[isbn].get(nom)
                if trouvaille is None:
                    continue
                verdict = trouvaille.verdict
                if verdict != "rien" and trouvaille.empreinte in faux:
                    verdict = "remplacement"
                comptes[verdict] += 1
                temps.append(trouvaille.ms)
                if verdict in ("couverture", "vignette"):
                    largeurs.append(trouvaille.largeur)
            if not temps:
                continue
            part = 100 * comptes["couverture"] // len(livres)
            px = int(statistics.median(largeurs)) if largeurs else 0
            ms = int(statistics.median(temps))
            trouvees = f"{comptes['couverture']} ({part} %)"
            print(f"      {nom:<16}{trouvees:>12}{comptes['vignette']:>10}"
                  f"{comptes['remplacement']:>10}{comptes['rien']:>7}"
                  f"{str(px) + ' px':>9}{str(ms) + ' ms':>9}")


def couverts(livres: list[str], mesures: dict, faux: set[str], noms: tuple[str, ...]) -> set[str]:
    """Livres pour lesquels au moins une des sources citées tient une vraie couverture."""
    return {
        isbn for isbn in livres
        if any((t := mesures[isbn].get(nom)) is not None and t.utilisable
               and t.empreinte not in faux for nom in noms)
    }


def main() -> int:
    arguments = sys.argv[1:]
    limite = next((int(a) for a in arguments if a.isdigit()), None)

    print(f"{'=' * 72}\nQUELLE SOURCE DÉTIENT LA COUVERTURE ?\n{'=' * 72}")

    print("\n1. Corpus.")
    corpus, origine = ([], "") if "--corpus" in arguments else lire_historique()
    if corpus:
        print(f"   {pluriel(len(corpus))} lus dans {origine} — votre collection.")
    else:
        corpus = list(CORPUS)
        raison = "demandé" if "--corpus" in arguments else "aucun historique trouvé"
        print(f"   Corpus embarqué ({raison}) : {len(corpus)} ISBN de notices réelles.")
        print("   Relancez-le depuis le dossier du projet pour mesurer VOS livres.")
    if limite:
        corpus = corpus[:limite]
    repartition = {z: sum(1 for i in corpus if aire(i) == z) for z in {aire(i) for i in corpus}}
    print(f"   {pluriel(len(corpus))} : "
          + ", ".join(f"{n} en « {z} »" for z, n in sorted(repartition.items())))

    print("\n2. Les sources répondent-elles depuis cette machine ?")
    print("   (un témoin dont on sait que la couverture existe)")
    muettes = []
    for nom, _, fabrique in SOURCES:
        temoin = TEMOINS.get(nom)
        if not temoin:
            print(f"      {nom:<16} pas de témoin — openBD n'est interrogé que sur les 978-4")
            continue
        trouvaille = interroger(fabrique, temoin)
        if trouvaille.utilisable and trouvaille.empreinte not in REMPLACEMENTS:
            etat = f"OK — {trouvaille.largeur} px en {trouvaille.ms} ms"
        elif trouvaille.verdict == "vignette":
            etat = f"vignette de {trouvaille.largeur} px seulement"
        elif trouvaille.empreinte in REMPLACEMENTS:
            etat = "image de remplacement — la source ne l'a pas"
        else:
            etat = "MUETTE depuis cette machine"
            muettes.append(nom)
        print(f"      {nom:<16} {temoin}  {etat}")
    if muettes:
        print(f"\n   Attention : {', '.join(muettes)} ne répond pas alors qu'elle devrait.")
        print("   Filtrage réseau, blocage par adresse ou motif d'URL changé : les")
        print("   chiffres qui suivent la sous-estiment. Signalez-le dans une issue.")

    duree = len(corpus) * 4 // 60 + 1
    print(f"\n3. Interrogation de {pluriel(len(corpus))} sur {len(SOURCES)} sources"
          f" (~{duree} min, une demi-seconde entre chaque livre).")
    print("   o couverture   v vignette trop petite   P image de remplacement   . rien")
    print("   (un remplacement encore inconnu apparaît en « o » ici et sera démasqué au bilan)\n")

    mesures: dict[str, dict[str, Trouvaille]] = {}
    for index, isbn in enumerate(corpus, 1):
        zone = aire(isbn)
        ligne = f"   {index:>3}/{len(corpus)}  {isbn}  {zone:<5}"
        mesures[isbn] = {}
        for nom, aires, fabrique in SOURCES:
            if aires is not None and zone not in aires:
                ligne += "  "
                continue
            trouvaille = interroger(fabrique, isbn)
            mesures[isbn][nom] = trouvaille
            ligne += {"couverture": "o ", "vignette": "v ",
                      "remplacement": "P ", "rien": ". "}[trouvaille.verdict]
        print(ligne, flush=True)
        time.sleep(0.5)

    faux = demasquer_remplacements(mesures)
    print(f"\n{'=' * 72}\nCE QUE CHAQUE SOURCE DÉTIENT\n{'=' * 72}")
    print(f"   Une couverture fait au moins {LARGEUR_MINIMALE} px de large ; en dessous")
    print("   c'est une vignette, comptée à part.")
    tableau_par_aire(corpus, mesures, faux)

    print(f"\n{'=' * 72}\nLA SEULE QUESTION QUI DÉCIDE\n{'=' * 72}")
    print("Combien de livres repartent avec une couverture, source après source ?\n")
    empilements = (
        ("aujourd'hui (BnF ∪ OpenLibrary ∪ openBD)", ("BnF", "OpenLibrary", "openBD")),
        ("+ ePagine", ("BnF", "OpenLibrary", "openBD", "ePagine")),
        ("+ Google zoom=3", ("BnF", "OpenLibrary", "openBD", "ePagine", "Google zoom=3")),
        ("+ Google zoom=1 (vignettes comprises)",
         ("BnF", "OpenLibrary", "openBD", "ePagine", "Google zoom=3", "Google zoom=1")),
    )
    gains: dict[str, dict[str, int]] = {}
    for zone in sorted({aire(i) for i in corpus}):
        livres = [i for i in corpus if aire(i) == zone]
        print(f"   aire « {zone} » — {pluriel(len(livres))}")
        gains[zone] = {}
        for etiquette, noms in empilements:
            atteints = couverts(livres, mesures, faux, noms)
            gains[zone][etiquette] = len(atteints)
            barre = "#" * (40 * len(atteints) // max(len(livres), 1))
            print(f"      {etiquette:<40}{len(atteints):>4}/{len(livres):<4}"
                  f"({100 * len(atteints) // max(len(livres), 1):>3} %) {barre}")
        print()

    print(f"{'=' * 72}\nVERDICT\n{'=' * 72}")
    for zone, resultat in gains.items():
        actuel = resultat["aujourd'hui (BnF ∪ OpenLibrary ∪ openBD)"]
        avec_epagine = resultat["+ ePagine"]
        avec_google = resultat["+ Google zoom=3"]
        total = max(sum(1 for i in corpus if aire(i) == zone), 1)
        pas_epagine = 100 * (avec_epagine - actuel) // total
        pas_google = 100 * (avec_google - avec_epagine) // total
        print(f"\n   aire « {zone} » : {100 * actuel // total} % des livres ont une couverture aujourd'hui.")
        if pas_epagine >= 15:
            print(f"      ePagine en apporte {pas_epagine} points de plus. Elle mérite un candidat,")
            print("      placé en tête : c'est une URL construite depuis l'ISBN, une seule")
            print("      requête, et la boucle de app/covers.py s'arrête au premier succès.")
        elif pas_epagine > 0:
            print(f"      ePagine n'apporte que {pas_epagine} points : à peser.")
        else:
            print("      ePagine n'apporte rien ici : ne pas l'ajouter pour cette aire.")
        if pas_google >= 10:
            print(f"      Google sans clé apporte encore {pas_google} points en 575 px : à retenir.")
        else:
            print(f"      Google sans clé n'apporte que {pas_google} points par-dessus : comme la")
            print("      Library of Congress, il coûterait une requête par scan pour presque rien.")

    rencontrees = sorted(
        empreinte for empreinte in faux
        if any(t.empreinte == empreinte for trouvailles in mesures.values()
               for t in trouvailles.values())
    )
    if rencontrees:
        nouvelles = [e for e in rencontrees if e not in REMPLACEMENTS]
        print(f"\n   Images de remplacement rencontrées ({len(nouvelles)} inconnues jusqu'ici) :")
        for empreinte in rencontrees:
            origine = REMPLACEMENTS.get(empreinte, "servie pour plusieurs livres de ce corpus")
            print(f"      {empreinte}  {origine}")
        if nouvelles:
            print("      Ajoutez les inconnues à REMPLACEMENTS en tête de ce fichier.")

    print("\n   Collez cette sortie dans une issue pour garder la trace de la mesure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
