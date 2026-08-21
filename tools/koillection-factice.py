#!/usr/bin/env python3
"""Koillection factice : juste assez d'API pour rejouer un ajout complet.

Reproduire un doublon demande un Koillection qui tombe en panne à la demande —
ce qu'on ne souhaite pas à son NAS. Ce serveur tient le rôle : il parle l'API
Platform que le client attend (jeton JWT, collections paginées, items, data,
tags, couverture) et se dérègle sur commande.

    python3 tools/koillection-factice.py            # écoute sur le port 8899

Les leviers de panne, via ``POST /_control/reset`` ou ``/_control/config`` :

    refuse_datum : le champ portant ce libellé est refusé (422), comme lorsque
                   Koillection recale un libellé en doublon
    fail_after   : passé ce nombre d'écritures de champs, les suivantes cassent
    slow_items   : lenteur du listing d'items, pour ouvrir la fenêtre de course

``GET /_control/state`` rend les items créés avec leurs champs — c'est là qu'on
lit combien d'exemplaires du même livre sont entrés.

Voir ``tools/banc-doublons.py``, qui déroule les scénarios contre ce serveur.
"""
from __future__ import annotations

import uuid
import asyncio

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

app = FastAPI()

PER_PAGE = 30

state = {
    "collections": {},   # id -> {"id", "title", "parent"}
    "items": {},         # id -> {"id", "name", "collection"}
    "data": {},          # item_id -> [ {label, value, type} ]
    "tags": {},
    "log": [],
    "refuse_datum": None,   # label refusé
    "fail_after": None,     # nombre de POST /api/data avant coupure
    "datum_calls": 0,
    "slow_items": 0.0,   # lenteur du listing d'items, comme sur un NAS chargé
}


def page_of(rows: list, page: int) -> dict:
    start = (page - 1) * PER_PAGE
    return {"hydra:member": rows[start:start + PER_PAGE], "hydra:totalItems": len(rows)}


@app.post("/_control/reset")
async def control_reset(request: Request):
    body = await request.json()
    state["collections"] = {}
    state["items"] = {}
    state["data"] = {}
    state["tags"] = {}
    state["log"] = []
    state["refuse_datum"] = body.get("refuse_datum")
    state["fail_after"] = body.get("fail_after")
    state["datum_calls"] = 0
    state["slow_items"] = body.get("slow_items", 0.0)
    for title in body.get("collections", []):
        cid = str(uuid.uuid4())
        state["collections"][cid] = {"id": cid, "title": title, "parent": None}
    return {"ok": True}


@app.post("/_control/config")
async def control_config(request: Request):
    """Change les leviers de panne sans effacer ce qui existe déjà."""
    body = await request.json()
    if "refuse_datum" in body:
        state["refuse_datum"] = body["refuse_datum"]
    if "slow_items" in body:
        state["slow_items"] = body["slow_items"]
    if "fail_after" in body:
        state["fail_after"] = body["fail_after"]
        state["datum_calls"] = 0
    return {"ok": True}


@app.get("/_control/state")
async def control_state():
    return {
        "items": [
            {**item, "data": state["data"].get(item["id"], [])}
            for item in state["items"].values()
        ],
        "collections": list(state["collections"].values()),
        "log": state["log"],
    }


@app.get("/api")
async def api_root():
    return {}


@app.post("/api/authentication_token")
async def token():
    return {"token": "jeton-de-test"}


@app.get("/api/collections")
async def collections(page: int = 1):
    rows = [
        {"id": c["id"], "title": c["title"],
         "parent": f"/api/collections/{c['parent']}" if c["parent"] else None}
        for c in state["collections"].values()
    ]
    return page_of(rows, page)


@app.post("/api/collections")
async def create_collection(request: Request):
    body = await request.json()
    cid = str(uuid.uuid4())
    parent = (body.get("parent") or "").rsplit("/", 1)[-1] or None
    state["collections"][cid] = {"id": cid, "title": body["title"], "parent": parent}
    return {"id": cid, "title": body["title"]}


@app.get("/api/collections/{collection_id}/items")
async def collection_items(collection_id: str, page: int = 1):
    if state["slow_items"]:
        await asyncio.sleep(state["slow_items"])
    rows = [
        {"id": i["id"], "name": i["name"]}
        for i in state["items"].values()
        if i["collection"] == collection_id
    ]
    return page_of(rows, page)


@app.post("/api/items")
async def create_item(request: Request):
    body = await request.json()
    item_id = str(uuid.uuid4())
    collection = (body.get("collection") or "").rsplit("/", 1)[-1]
    state["items"][item_id] = {"id": item_id, "name": body["name"], "collection": collection}
    state["log"].append(f"POST /api/items {body['name']!r}")
    return {"id": item_id, "name": body["name"]}


@app.post("/_control/rename")
async def control_rename(request: Request):
    """Renomme un item, comme le ferait l'utilisateur depuis Koillection."""
    body = await request.json()
    state["items"][body["item_id"]]["name"] = body["name"]
    return {"ok": True}


@app.get("/api/items/{item_id}")
async def get_item(item_id: str):
    item = state["items"].get(item_id)
    if item is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return {"id": item["id"], "name": item["name"]}


@app.get("/api/items/{item_id}/data")
async def item_data(item_id: str, page: int = 1):
    return page_of(state["data"].get(item_id, []), page)


@app.post("/api/data")
async def create_datum(request: Request):
    body = await request.json()
    state["datum_calls"] += 1
    label = body.get("label")
    if state["fail_after"] is not None and state["datum_calls"] > state["fail_after"]:
        # Coupure brutale : c'est ce que voit le client quand le NAS décroche.
        raise RuntimeError("connexion coupée par le serveur (simulation)")
    if state["refuse_datum"] and label == state["refuse_datum"]:
        state["log"].append(f"REFUS champ {label!r}")
        return JSONResponse({"detail": f"{label} refusé"}, status_code=422)
    item_id = (body.get("item") or "").rsplit("/", 1)[-1]
    state["data"].setdefault(item_id, []).append(
        {"label": label, "value": body.get("value"), "type": body.get("type")}
    )
    return {"id": str(uuid.uuid4())}


@app.get("/api/tags")
async def tags(page: int = 1):
    return page_of(list(state["tags"].values()), page)


@app.post("/api/tags")
async def create_tag(request: Request):
    body = await request.json()
    tid = str(uuid.uuid4())
    state["tags"][tid] = {"id": tid, "label": body["label"]}
    return {"id": tid, "label": body["label"]}


@app.post("/api/items/{item_id}/image")
async def upload_image(item_id: str):
    return Response(status_code=201)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8899, log_level="critical")
