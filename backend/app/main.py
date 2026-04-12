from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import SessionLocal, engine, Base
from app.routers import admin, auth, chat, documents, meta
from app.seed import init_extensions, seed_if_empty

settings = get_settings()
_log = logging.getLogger(__name__)

app = FastAPI(title="ООО «ЭДДА» — корпоративная база знаний", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(meta.router, prefix="/api")


@app.on_event("startup")
def _startup():
    if os.environ.get("EDDA_USE_HASH_EMBEDDINGS", "").strip().lower() in ("1", "true", "yes"):
        _log.warning(
            "EDDA_USE_HASH_EMBEDDINGS включён: эмбеддинги без PyTorch (~512MB RAM). "
            "Качество семантического поиска ниже; для полноценного RAG отключите и используйте инстанс ≥2GB RAM."
        )
    _log.info(
        "CORS: %d origin(s), regex=%s",
        len(settings.cors_origins_list),
        bool(settings.cors_origin_regex),
    )
    os.makedirs(settings.upload_dir, exist_ok=True)
    if "sqlite" in settings.database_url:
        (Path(__file__).resolve().parent.parent / "data").mkdir(parents=True, exist_ok=True)
    init_extensions(engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# --- SPA static (production / docker): set FRONTEND_DIST to built Vite `dist` folder ---
def _dist_dir() -> str | None:
    d = os.environ.get("FRONTEND_DIST")
    if d and os.path.isdir(d):
        return d
    here = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(here):
        return here
    return None


_dist = _dist_dir()
if _dist:
    assets = os.path.join(_dist, "assets")
    if os.path.isdir(assets):
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        # API обслуживается отдельными маршрутами выше
        segs = full_path.strip("/").split("/")
        if segs and segs[0] == "api":
            raise HTTPException(status_code=404)
        fp = os.path.join(_dist, full_path)
        if full_path and os.path.isfile(fp):
            return FileResponse(fp)
        index = os.path.join(_dist, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        raise HTTPException(status_code=404)
