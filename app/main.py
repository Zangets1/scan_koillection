"""Application FastAPI : API de recherche ISBN + envoi vers Koillection + PWA."""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import covers
from . import isbn as isbn_utils
from .config import get_settings
from .history import History
from .importer import Importer
from .koillection import KoillectionClient, KoillectionError
from .lookup import LookupService
from .models import AddRequest, AddResponse, LookupResponse

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("scan-koillection")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
VERSION = os.environ.get("APP_VERSION", "1.0.0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    lookup = LookupService(settings)
    koillection = KoillectionClient(settings)
    history = History(os.environ.get("DATA_DIR", "/data") + "/history.sqlite3")

    await lookup.startup()
    await koillection.startup()
    await history.init()

    app.state.settings = settings
    app.state.lookup = lookup
    app.state.koillection = koillection
    app.state.history = history
    app.state.importer = Importer(settings, koillection, history, lookup)

    logger.info(
        "Démarrage — fournisseurs : %s | Koillection : %s",
        ", ".join(p.label for p in lookup.providers) or "aucun",
        settings.koillection_url or "non configuré",
    )
    try:
        yield
    finally:
        await lookup.shutdown()
        await koillection.shutdown()


app = FastAPI(
    title="Scan Koillection",
    version=VERSION,
    description="Scanner d'ISBN qui alimente Koillection depuis la BnF, OpenLibrary et openBD.",
    lifespan=lifespan,
)

_settings = get_settings()
app.add_middleware(
    SessionMiddleware,
    secret_key=_settings.session_secret or secrets.token_urlsafe(32),
    session_cookie="scan_koillection",
    max_age=_settings.session_days * 86400,
    same_site="lax",
    https_only=False,
)


# ----------------------------------------------------------------------
# Authentification facultative
# ----------------------------------------------------------------------
class LoginRequest(BaseModel):
    password: str


def require_auth(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.app_password:
        return
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Authentification requise.")


Auth = Annotated[None, Depends(require_auth)]


@app.post("/api/login")
async def login(request: Request, body: LoginRequest) -> dict:
    settings = request.app.state.settings
    if not settings.app_password:
        return {"ok": True}
    if not secrets.compare_digest(body.password, settings.app_password):
        raise HTTPException(status_code=401, detail="Mot de passe incorrect.")
    request.session["authenticated"] = True
    return {"ok": True}


@app.post("/api/logout")
async def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


# ----------------------------------------------------------------------
# Configuration exposée au front
# ----------------------------------------------------------------------
@app.get("/api/config")
async def config(request: Request) -> dict:
    settings = request.app.state.settings
    lookup: LookupService = request.app.state.lookup
    return {
        "version": VERSION,
        "auth_required": bool(settings.app_password),
        "authenticated": bool(request.session.get("authenticated")) or not settings.app_password,
        "koillection_configured": settings.koillection_configured,
        "koillection_url": settings.koillection_url,
        "default_collection": settings.default_collection,
        "series_subcollections": settings.series_subcollections,
        "providers": [{"name": p.name, "label": p.label} for p in lookup.providers],
    }


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "version": VERSION}


# ----------------------------------------------------------------------
# Recherche
# ----------------------------------------------------------------------
@app.get("/api/lookup/{raw_isbn}", response_model=LookupResponse)
async def lookup_isbn(request: Request, raw_isbn: str, refresh: bool = False) -> LookupResponse:
    try:
        isbn13 = isbn_utils.normalize(raw_isbn)
    except isbn_utils.InvalidISBN as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    service: LookupService = request.app.state.lookup
    result = await service.lookup(isbn13, use_cache=not refresh)

    history: History = request.app.state.history
    previous = await history.find(isbn13)
    if previous:
        result.message = (
            f"Déjà ajouté le {previous['created_at'][:10]} dans « {previous['collection']} »."
        )
    return result


@app.get("/api/cover/{raw_isbn}")
async def cover(request: Request, raw_isbn: str) -> Response:
    try:
        isbn13 = isbn_utils.normalize(raw_isbn)
    except isbn_utils.InvalidISBN as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    service: LookupService = request.app.state.lookup
    result = await service.lookup(isbn13)
    candidates = result.book.cover_candidates if result.book else []
    image = await covers.resolve(service.client, candidates)
    if image is None:
        raise HTTPException(status_code=404, detail="Aucune couverture disponible.")
    return Response(
        content=image.content,
        media_type=image.content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ----------------------------------------------------------------------
# Koillection
# ----------------------------------------------------------------------
@app.get("/api/collections")
async def collections(request: Request, _: Auth, refresh: bool = False) -> list[dict]:
    client: KoillectionClient = request.app.state.koillection
    try:
        entries = await client.collections(refresh=refresh)
    except KoillectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [entry.model_dump() for entry in entries]


@app.post("/api/add", response_model=AddResponse)
async def add(request: Request, body: AddRequest, _: Auth) -> AddResponse:
    importer: Importer = request.app.state.importer
    try:
        return await importer.add(body)
    except KoillectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/history")
async def history(request: Request, _: Auth, limit: int = 30) -> list[dict]:
    store: History = request.app.state.history
    return await store.recent(min(max(limit, 1), 200))


# ----------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------
@app.exception_handler(404)
async def not_found(request: Request, exc: Exception) -> Response:
    # Les routes inconnues sous /api restent des 404 JSON ; le reste retombe
    # sur la page unique de la PWA.
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Ressource inconnue."}, status_code=404)
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
