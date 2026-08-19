#!/usr/bin/env python3
"""La Library of Congress mérite-t-elle une requête par scan anglophone ?

Qu'un serveur réponde ne dit rien de ce qu'il apporte. K10plus répondait très
bien sur les ISBN français — et n'y comblait aucun champ que la BnF et le SUDOC
n'aient déjà : la mesure a évité d'ajouter 205 ms par scan pour rien. Ce script
pose la même question à la Library of Congress.

Il interroge, sur les 55 ISBN anglophones du banc d'essai du projet :

    · la Library of Congress   (SRU, port 210, en clair)
    · OpenLibrary              (déjà en place)
    · K10plus                  (ajouté en v2)

puis compare. La question n'est pas « la LC répond-elle » mais « comble-t-elle
des champs que les deux autres laissent vides ».

    python3 mesure-loc.py              # les 55 ISBN, environ trois minutes
    python3 mesure-loc.py 12           # les 12 premiers, pour aller vite

À lancer DEPUIS LA MACHINE qui fera les requêtes : le port 210 est filtré sur
beaucoup de réseaux, et c'est invérifiable ailleurs.

Sans aucune dépendance : urllib et xml de la bibliothèque standard, rien à
installer. Le lecteur MARC21 ci-dessous reprend volontairement un sous-ensemble
de app/providers/marc21.py plutôt que de l'importer : ce script doit pouvoir
tourner sur n'importe quelle machine, sans le dépôt ni pydantic ni httpx.
"""
import json
import socket
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET

# Ne jamais imposer un encodage à la console : forcer l'UTF-8 sur une console
# Windows en cp1252 produit du « rÃ©pond » là où l'on voulait « répond ». On
# garde donc son encodage et on se contente de neutraliser les caractères
# qu'elle ne sait pas écrire — le texte reste lisible partout.
if hasattr(sys.stdout, "reconfigure"):  # Python 3.7+
    sys.stdout.reconfigure(errors="replace")

MARC = "{http://www.loc.gov/MARC21/slim}"
UA = "scan-koillection/2.0 (+https://github.com/zangets1/scan_koillection) mesure ponctuelle"

#: Les 55 ISBN anglophones du banc d'essai, tirés de notices réelles.
CORPUS = [
    "9781526650863", "9781526628220", "9781526635365", "9781526657077", "9781408883358",
    "9781408884447", "9780571212682", "9780735281264", "9780571302208", "9780865479593",
    "9780571303335", "9780141186917", "9780605938298", "9781423163008", "9780141341569",
    "9780141337142", "9780140116625", "9780752864327", "9781938570353", "9780575091504",
    "9780575087743", "9781250238429", "9781590710036", "9781407186009", "9781338126198",
    "9781338804737", "9780836218220", "9781423151289", "9780545611275", "9780345272157",
    "9780345533234", "9780345315328", "9781880418536", "9780345519474", "9780345334695",
    "9781797127972", "9781471198144", "9780241753859", "9781442426788", "9781797147963",
    "9781471166792", "9781857157246", "9780385354288", "9781400043873", "9780375966668",
    "9781529059960", "9780307700001", "9780765380722", "9781250838865", "9780312875626",
    "9780765331960", "9780765316974", "9780765391353", "9780747532743", "9780590353403",
]

#: Codes pays MARC (zone 008/15-17) -> pays lisible, réduits à l'essentiel ici.
COUNTRIES = {
    "xxu": "États-Unis", "nyu": "États-Unis", "cau": "États-Unis", "mau": "États-Unis",
    "ilu": "États-Unis", "pau": "États-Unis", "mnu": "États-Unis", "txu": "États-Unis",
    "nju": "États-Unis", "enk": "Royaume-Uni", "xxk": "Royaume-Uni", "stk": "Royaume-Uni",
    "wlk": "Royaume-Uni", "nik": "Royaume-Uni", "fr": "France", "ja": "Japon",
    "gw": "Allemagne", "it": "Italie", "sp": "Espagne", "cn": "Canada", "at": "Australie",
}

#: Champs comparés. Le pays est le seul que ni l'ISBN ni OpenLibrary ne donnent.
CHAMPS = ("titre", "auteur", "editeur", "pages", "serie", "pays")


def fetch(url: str, timeout: int = 15) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None


# ----------------------------------------------------------------------
# Lecture MARC21, réduite aux champs comparés
# ----------------------------------------------------------------------
def lire_marc(xml_text: str) -> dict | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    for record in root.iter(f"{MARC}record"):
        fiche = dict.fromkeys(CHAMPS)

        for control in record.iter(f"{MARC}controlfield"):
            if control.get("tag") == "008" and control.text:
                code = control.text[15:18].strip().lower()
                fiche["pays"] = COUNTRIES.get(code)

        for field in record.iter(f"{MARC}datafield"):
            tag = field.get("tag")
            subs = {s.get("code"): (s.text or "").strip()
                    for s in field.iter(f"{MARC}subfield") if (s.text or "").strip()}
            if tag == "245" and not fiche["titre"]:
                fiche["titre"] = subs.get("a")
            elif tag == "100" and not fiche["auteur"]:
                fiche["auteur"] = subs.get("a")
            elif tag in ("264", "260") and not fiche["editeur"]:
                fiche["editeur"] = subs.get("b")
            elif tag == "300" and not fiche["pages"]:
                fiche["pages"] = subs.get("a")
            elif tag in ("830", "490") and not fiche["serie"] and subs.get("v"):
                fiche["serie"] = subs.get("a")

        if fiche["titre"]:
            return fiche
    return None


# ----------------------------------------------------------------------
# Les trois sources
# ----------------------------------------------------------------------
def isbn10(isbn13: str) -> str | None:
    """« 9780590353403 » -> « 0590353403 ».

    Une notice de 1997 ne porte que l'ISBN-10 en zone 020 : chercher la forme à
    treize chiffres n'y trouve rien. Les catalogues de bibliothèque sont pleins
    de notices anciennes jamais reprises.
    """
    if len(isbn13) != 13 or not isbn13.startswith("978") or not isbn13.isdigit():
        return None
    corps = isbn13[3:12]
    total = sum((10 - i) * int(c) for i, c in enumerate(corps))
    cle = (11 - total % 11) % 11
    return corps + ("X" if cle == 10 else str(cle))


def _url_loc(isbn: str) -> str:
    params = urllib.parse.urlencode({
        "version": "1.1", "operation": "searchRetrieve",
        # `bath.isbn` est l'index ISBN du profil Bath, celui que la LC documente.
        "query": f"bath.isbn={isbn}", "maximumRecords": "1", "recordSchema": "marcxml"})
    return f"http://lx2.loc.gov:210/LCDB?{params}"


def loc(isbn: str) -> dict | None:
    """Interroge la LC sur les deux formes de l'ISBN.

    L'index est littéral : une notice qui ne porte que l'ISBN-10 reste
    introuvable si l'on ne cherche que la forme à treize chiffres.
    """
    for forme in (isbn, isbn10(isbn)):
        if not forme:
            continue
        body = fetch(_url_loc(forme))
        fiche = lire_marc(body) if body else None
        if fiche:
            return fiche
    return None


def diagnostic_sru(xml_text: str) -> str | None:
    """Message d'erreur renvoyé par le serveur SRU, s'il en renvoie un.

    Sans cette lecture, un nom d'index refusé ressemblerait à « aucune notice » :
    le script conclurait « apport nul » là où la question n'a jamais été posée.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return "réponse illisible (ce n'est pas du XML)"
    for balise in ("message", "diagnostic"):
        for element in root.iter():
            if element.tag.endswith(f"}}{balise}") or element.tag == balise:
                texte = (element.text or "").strip()
                if texte:
                    return texte
    return None


def k10plus(isbn: str) -> dict | None:
    params = urllib.parse.urlencode({
        "version": "1.1", "operation": "searchRetrieve",
        "query": f"pica.isb={isbn}", "maximumRecords": "1", "recordSchema": "marcxml"})
    body = fetch(f"https://sru.k10plus.de/opac-de-627?{params}")
    return lire_marc(body) if body else None


def openlibrary(isbn: str) -> dict | None:
    body = fetch(f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}"
                 f"&format=json&jscmd=data")
    if not body:
        return None
    try:
        payload = (json.loads(body) or {}).get(f"ISBN:{isbn}")
    except ValueError:
        return None
    if not payload or not payload.get("title"):
        return None
    editeurs = payload.get("publishers") or []
    return {
        "titre": payload.get("title"),
        "auteur": (payload.get("authors") or [{}])[0].get("name"),
        "editeur": editeurs[0].get("name") if editeurs else None,
        "pages": payload.get("number_of_pages"),
        "serie": None,          # OpenLibrary ne l'expose pas ici
        "pays": None,           # ni le pays d'édition : c'est tout le sujet
    }


SOURCES = (("Library of Congress", loc), ("OpenLibrary", openlibrary), ("K10plus", k10plus))


# ----------------------------------------------------------------------
def main() -> int:
    limite = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else len(CORPUS)
    corpus = CORPUS[:limite]

    print("1. Le port 210 de la Library of Congress répond-il ?", end=" ", flush=True)
    try:
        with socket.create_connection(("lx2.loc.gov", 210), timeout=10):
            print("oui.")
    except OSError as exc:
        print(f"NON — {exc}")
        print("   Le port est filtré : la Library of Congress est hors de portée")
        print("   depuis cette machine. Rien d'autre à mesurer.")
        return 1

    # Requêtes d'essai avant les cinquante-cinq. Deux pièges à écarter : un
    # serveur qui refuse la syntaxe (il répond par un diagnostic, pas par une
    # erreur HTTP), et un index littéral qui ne connaît que l'ISBN-10. Les deux
    # ressembleraient à « aucune notice » et fausseraient toute la mesure.
    #
    # Les témoins sont des éditions AMÉRICAINES : la Library of Congress
    # catalogue le dépôt légal des États-Unis, pas les tirages britanniques.
    temoins = [
        ("9780590353403", "Harry Potter, Scholastic, New York"),
        ("9780307700001", "The Buddha in the attic, Knopf, New York"),
        ("9780345391803", "Hitchhiker's Guide, Ballantine, New York"),
    ]
    print("   Requêtes d'essai sur des éditions américaines connues :")
    formes_qui_marchent = []
    for code, description in temoins:
        for etiquette, forme in (("ISBN-13", code), ("ISBN-10", isbn10(code))):
            if not forme:
                continue
            reponse = fetch(_url_loc(forme))
            if reponse is None:
                verdict = "pas de réponse"
            elif (souci := diagnostic_sru(reponse)):
                verdict = f"le serveur proteste : {souci}"
            elif lire_marc(reponse) is None:
                verdict = "aucune notice"
            else:
                verdict = "TROUVÉ"
                formes_qui_marchent.append(etiquette)
            print(f"      {etiquette} {forme:<14} {verdict}   ({description})")
            time.sleep(0.5)

    if not formes_qui_marchent:
        print("\n   Aucun de ces trois livres américains n'est trouvé. Le service répond")
        print("   mais la recherche ne donne rien : l'index a probablement changé de nom.")
        print("   Collez ces lignes dans l'issue #3, le script sera corrigé en conséquence.")
        return 1
    print(f"\n   Formes qui aboutissent : {', '.join(sorted(set(formes_qui_marchent)))}.")

    print(f"\n2. Interrogation de {len(corpus)} ISBN anglophones sur trois sources.")
    print("   (une seconde entre chaque livre, pour rester poli avec les serveurs)\n")

    resultats: dict[str, list] = {nom: [] for nom, _ in SOURCES}
    temps: dict[str, list] = {nom: [] for nom, _ in SOURCES}

    for index, isbn in enumerate(corpus, 1):
        ligne = f"   {index:>2}/{len(corpus)}  {isbn}  "
        for nom, source in SOURCES:
            debut = time.perf_counter()
            fiche = source(isbn)
            temps[nom].append((time.perf_counter() - debut) * 1000)
            resultats[nom].append(fiche)
            ligne += "o" if fiche else "."
        print(ligne, flush=True)
        time.sleep(1)

    # --- Ce que chaque source trouve, et en combien de temps ---------
    print(f"\n{'=' * 72}\nCE QUE CHAQUE SOURCE RAPPORTE\n{'=' * 72}")
    print(f"{'source':<22}{'trouvé':>10}{'médiane':>10}   " +
          "".join(f"{c:>9}" for c in CHAMPS[1:]))
    for nom, _ in SOURCES:
        trouves = [f for f in resultats[nom] if f]
        med = int(statistics.median(temps[nom])) if temps[nom] else 0
        taux = "".join(
            f"{(100 * sum(1 for f in trouves if f.get(c)) // len(trouves)) if trouves else 0:>8}%"
            for c in CHAMPS[1:])
        print(f"{nom:<22}{f'{len(trouves)}/{len(corpus)}':>10}{f'{med} ms':>10}   {taux}")

    # --- La seule question qui décide -------------------------------
    print(f"\n{'=' * 72}\nAPPORT PROPRE DE LA LIBRARY OF CONGRESS\n{'=' * 72}")
    print("Champs qu'elle renseigne alors qu'OpenLibrary ET K10plus les laissent vides :\n")

    gains = dict.fromkeys(CHAMPS, 0)
    livres_inedits = 0
    for index in range(len(corpus)):
        fiche_loc = resultats["Library of Congress"][index]
        autres = [resultats["OpenLibrary"][index], resultats["K10plus"][index]]
        if not fiche_loc:
            continue
        if not any(autres):
            livres_inedits += 1
            continue
        for champ in CHAMPS:
            if fiche_loc.get(champ) and not any(f.get(champ) for f in autres if f):
                gains[champ] += 1

    for champ in CHAMPS:
        barre = "#" * gains[champ]
        print(f"   {champ:<10} +{gains[champ]:<3} {barre}")
    print(f"\n   livres qu'elle seule connaît : {livres_inedits}")

    total = sum(gains.values())
    print(f"\n{'=' * 72}\nVERDICT\n{'=' * 72}")
    if livres_inedits == 0 and total < len(corpus) * 0.15:
        print("   Apport marginal. Elle coûterait une requête par scan anglophone")
        print("   pour presque rien : ne pas l'ajouter, et fermer l'issue #3.")
    else:
        print("   Apport réel. Elle mérite un fournisseur — le lecteur MARC21 du")
        print("   projet (app/providers/marc21.py) sait déjà lire son format.")
    print("\n   Collez cette sortie dans l'issue #3 pour garder la trace de la mesure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
