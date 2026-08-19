#!/usr/bin/env python3
"""Le catalogue de la Library of Congress est-il joignable depuis VOTRE serveur ?

La LC n'expose son SRU que sur http://lx2.loc.gov:210 — en clair, sur un port
non standard. Beaucoup de réseaux le bloquent, et c'est invérifiable ailleurs
que depuis la machine qui fera les requêtes.

    python3 test-loc.py            # trois ISBN témoins
    python3 test-loc.py 9780306406157

Sans dépendance : urllib seul, exécutable sur le NAS tel quel. Fonctionne aussi
sous Windows, PowerShell compris.
"""
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET

# Les consoles Windows écrivent encore en cp1252, qui ne connaît pas la flèche
# « → » employée plus bas. Sans cette ligne, le script s'interromprait sur un
# UnicodeEncodeError au lieu de répondre à la question posée. `errors="replace"`
# couvre les consoles plus anciennes encore : un caractère de remplacement vaut
# mieux qu'une pile d'appels.
if hasattr(sys.stdout, "reconfigure"):  # Python 3.7+
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://lx2.loc.gov:210/LCDB"
MARC = "{http://www.loc.gov/MARC21/slim}"
TEMOINS = ["9780747532743", "9780590353403", "9780345391803"]


def joignable() -> bool:
    print("1. Ouverture d'une connexion TCP vers lx2.loc.gov:210 …", end=" ", flush=True)
    t0 = time.perf_counter()
    try:
        with socket.create_connection(("lx2.loc.gov", 210), timeout=10):
            print(f"OK ({time.perf_counter()-t0:.2f} s)")
            return True
    except OSError as exc:
        print(f"ÉCHEC — {exc}")
        print("   → le port 210 est filtré (pare-feu, FAI ou réseau Docker).")
        print("     La Library of Congress n'est pas utilisable depuis cette machine.")
        return False


def interroge(isbn: str) -> None:
    params = urllib.parse.urlencode({
        "version": "1.1", "operation": "searchRetrieve",
        "query": f"bath.isbn={isbn}", "maximumRecords": "1",
        "recordSchema": "marcxml"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(f"{BASE}?{params}", timeout=15) as response:
            body = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        print(f"   {isbn}  ÉCHEC ({time.perf_counter()-t0:.2f} s) — {exc}")
        return
    dt = time.perf_counter() - t0
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        print(f"   {isbn}  réponse illisible ({dt:.2f} s)")
        return
    titre = auteur = pays = "—"
    for record in root.iter(f"{MARC}record"):
        for field in record.iter(f"{MARC}datafield"):
            tag = field.get("tag")
            for sub in field.iter(f"{MARC}subfield"):
                if tag == "245" and sub.get("code") == "a":
                    titre = (sub.text or "").strip()[:46]
                if tag == "100" and sub.get("code") == "a":
                    auteur = (sub.text or "").strip()[:26]
        for control in record.iter(f"{MARC}controlfield"):
            if control.get("tag") == "008" and control.text:
                pays = control.text[15:18].strip() or "—"
        break
    trouve = "trouvé" if titre != "—" else "inconnu"
    print(f"   {isbn}  {trouve:<8} {dt:5.2f} s  pays(MARC 008)={pays:<4} « {titre} » — {auteur}")


def main() -> int:
    isbns = sys.argv[1:] or TEMOINS
    if not joignable():
        return 1
    print(f"\n2. Recherche de {len(isbns)} ISBN dans le catalogue LCDB :")
    for isbn in isbns:
        interroge(isbn)
    print("\nSi les trois lignes affichent « trouvé » en moins de 2 s, la Library of")
    print("Congress est exploitable ici. Sinon, s'en tenir à OpenLibrary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
