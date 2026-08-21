#!/usr/bin/env python3
"""Banc d'essai : le même livre entre-t-il une seule fois, quoi qu'il arrive ?

Six scénarios, joués de bout en bout en HTTP contre un Koillection factice.
Quatre d'entre eux rejouent des pannes réelles qui fabriquaient des doublons —
le champ ISBN refusé, la connexion qui casse au milieu, la double validation,
la fiche renommée à la main. Les deux derniers vérifient qu'on n'a pas serré
la vis trop fort : deux livres qui portent le même titre doivent rester deux
livres, et un second exemplaire demandé explicitement doit passer.

Trois fenêtres :

    python3 tools/koillection-factice.py                       # le faux NAS
    KOILLECTION_URL=http://127.0.0.1:8899 \\
      KOILLECTION_USERNAME=x KOILLECTION_PASSWORD=y \\
      UPLOAD_COVER=false DATA_DIR=/tmp/banc \\
      python3 -m uvicorn app.main:app --port 8898
    python3 tools/banc-doublons.py 8898

Le script sort en échec dès qu'un scénario crée un item de trop : il tient donc
dans une CI aussi bien que sous les yeux.
"""
from __future__ import annotations

import asyncio
import sys

import httpx

KOI = "http://127.0.0.1:8899"
APP = f"http://127.0.0.1:{sys.argv[1] if len(sys.argv) > 1 else 8898}"

LIVRE = {
    "title": "Trois vies par semaine",
    "authors": ["Michel Bussi"],
    "publisher": "Presses de la Cité",
    "read": True,
    "collection": "Livres lus",
}


async def reset(client, **kwargs):
    await client.post(f"{KOI}/_control/reset", json={"collections": ["Livres lus"], **kwargs})


async def config(client, **kwargs):
    await client.post(f"{KOI}/_control/config", json=kwargs)


async def etat(client):
    return (await client.get(f"{KOI}/_control/state")).json()


async def ajouter(client, isbn, **extra):
    try:
        response = await client.post(f"{APP}/api/add", json={**LIVRE, "isbn13": isbn, **extra})
        return response.status_code, response.json()
    except Exception as exc:  # noqa: BLE001
        return 0, {"detail": f"{exc.__class__.__name__}: {exc}"}


def dire(code, corps):
    marque = "doublon signalé" if corps.get("duplicate") else "ajouté"
    return f"{code} [{marque}] {corps.get('message') or corps.get('detail')}"


def verdict(titre, items, attendu, resultats):
    ok = len(items) == attendu
    print(f"\n[{'OK' if ok else 'ÉCHEC'}] {titre} — {len(items)} item(s), attendu {attendu}")
    for item in items:
        labels = [d["label"] for d in item["data"]]
        print(f"          · {item['name']!r} champs = {labels or '(aucun)'}")
    resultats.append(ok)


async def main():
    resultats: list[bool] = []
    async with httpx.AsyncClient(timeout=60) as client:
        print(f"### banc lancé contre {APP}")

        # ── A · quatre validations simultanées ────────────────────────
        print("\n=== A · quatre POST /api/add simultanés (NAS lent) ===")
        await reset(client, slow_items=0.3)
        for code, corps in await asyncio.gather(*[ajouter(client, "9782258201804") for _ in range(4)]):
            print("   ", dire(code, corps))
        verdict("A · double validation simultanée", (await etat(client))["items"], 1, resultats)

        # ── B · Koillection refuse le champ ISBN ──────────────────────
        print("\n=== B · le champ ISBN est refusé, trois scans successifs ===")
        await reset(client, refuse_datum="ISBN")
        for essai in range(3):
            print(f"    scan {essai + 1} :", dire(*await ajouter(client, "9782258201804")))
        verdict("B · fiche sans ISBN puis rescan", (await etat(client))["items"], 1, resultats)

        # ── C · coupure au milieu de l'ajout ──────────────────────────
        print("\n=== C · Koillection décroche pendant l'écriture des champs ===")
        await reset(client, fail_after=0)
        print("    essai 1 :", dire(*await ajouter(client, "9782258201804")))
        await config(client, fail_after=None)
        print("    essai 2 :", dire(*await ajouter(client, "9782258201804")))
        verdict("C · coupure puis nouvel essai", (await etat(client))["items"], 1, resultats)

        # ── D · l'item a été renommé dans Koillection ─────────────────
        print("\n=== D · fiche renommée à la main, puis rescannée ===")
        await reset(client)
        print("    scan 1 :", dire(*await ajouter(client, "9782258201804")))
        item_id = (await etat(client))["items"][0]["id"]
        await client.post(f"{KOI}/_control/rename",
                          json={"item_id": item_id, "name": "Bussi - Trois vies par semaine"})
        print("    scan 2 :", dire(*await ajouter(client, "9782258201804")))
        verdict("D · fiche renommée", (await etat(client))["items"], 1, resultats)

        # ── E · deux livres différents portant le même titre ──────────
        print("\n=== E · deux livres homonymes, ISBN différents ===")
        await reset(client)
        print("    livre 1 :", dire(*await ajouter(client, "9782258201804")))
        print("    livre 2 :", dire(*await ajouter(client, "9782070368228")))
        verdict("E · homonymes non confondus", (await etat(client))["items"], 2, resultats)

        # ── F · l'utilisateur force volontairement un second exemplaire ─
        print("\n=== F · second exemplaire demandé explicitement ===")
        await reset(client)
        print("    scan 1 :", dire(*await ajouter(client, "9782258201804")))
        print("    forcé  :", dire(*await ajouter(client, "9782258201804", force=True)))
        verdict("F · ajout forcé toujours possible", (await etat(client))["items"], 2, resultats)

    print("\n" + "=" * 64)
    print("RÉSULTAT :", "tout est conforme" if all(resultats) else "bug reproduit")
    return 0 if all(resultats) else 1


sys.exit(asyncio.run(main()))
