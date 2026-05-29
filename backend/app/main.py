from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import SessionLocal, engine, Base
from app.routers import (
    admin,
    auth,
    chat,
    documents,
    meta,
    notifications as notifications_router,
    requests as requests_router,
)
from app.services.llm import probe_gemini
from app.seed import (
    apply_sql_migrations,
    init_extensions,
    seed_if_empty,
    seed_requests_demo,
)

settings = get_settings()
_log = logging.getLogger(__name__)

# Отдельное приложение под /api — иначе catch-all GET /{full_path} перехватывает все пути и POST /api/... даёт 405.
api_app = FastAPI(title="ООО «ЭДДА» — API", version="1.0.0")

api_app.include_router(auth.router, prefix="")
api_app.include_router(documents.router, prefix="")
api_app.include_router(chat.router, prefix="")
api_app.include_router(admin.router, prefix="")
api_app.include_router(meta.router, prefix="")
api_app.include_router(requests_router.router, prefix="")
api_app.include_router(notifications_router.router, prefix="")


@api_app.get("/health/llm")
async def health_llm():
    """Публичная проверка: задан ли ключ и принимает ли его Google (без раскрытия секрета)."""
    probe = await probe_gemini(settings)
    return {
        "gemini_configured": probe["configured"],
        "gemini_ok": probe["ok"],
        "detail": probe["detail"],
    }


@api_app.get("/health")
def health():
    return {"status": "ok"}


app = FastAPI(title="ООО «ЭДДА» — корпоративная база знаний", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/api", api_app)


def _is_paas_env() -> bool:
    """Render/Railway/Fly выставляют свои маркеры — используем их, чтобы отличить локальный запуск от прод."""
    return any(
        os.environ.get(k)
        for k in ("RENDER", "RENDER_SERVICE_ID", "RAILWAY_ENVIRONMENT", "FLY_APP_NAME")
    )


@app.on_event("startup")
async def _startup():
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
    if settings.gemini_api_key:
        k = settings.gemini_api_key
        _log.info("LLM: Gemini key loaded (%s…%s)", k[:6], k[-4:])
        try:
            probe = await probe_gemini(settings)
            if probe["ok"]:
                _log.info("LLM: Gemini probe OK")
            else:
                _log.warning("LLM: Gemini probe failed — %s", probe["detail"])
        except Exception as e:
            _log.warning("LLM: Gemini probe error — %s", e)
    elif settings.openai_api_key:
        _log.info("LLM: OpenAI key loaded")
    else:
        _log.warning(
            "LLM: GEMINI_API_KEY / OPENAI_API_KEY не заданы — чат будет в режиме только фрагментов."
        )
    # Fail-fast: в облаке без DATABASE_URL подставится дефолт 127.0.0.1:5432 → длинный
    # стек "Connection refused". Лучше сразу выдать понятное сообщение.
    raw_db_url = os.environ.get("DATABASE_URL", "").strip()
    if _is_paas_env() and not raw_db_url:
        raise RuntimeError(
            "DATABASE_URL не задан. На Render: Dashboard → ваш Postgres (например edda-db) → "
            "Connect → скопировать Internal Database URL → в сервисе edda-portal-* → "
            "Environment → добавить переменную DATABASE_URL и сделать Manual Deploy."
        )
    os.makedirs(settings.upload_dir, exist_ok=True)
    init_extensions(engine)
    # Сначала идемпотентная схема-миграция (добавляет недостающие колонки и таблицы
    # в уже существующих БД — например users.department_id),
    # потом create_all для полноты, потом seed.
    apply_sql_migrations(engine, ["002_extended_schema.sql", "004_requests.sql"])
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
        # Идемпотентный «add-on seed» для подсистемы заявок:
        # проставляет department_id существующим пользователям и досоздаёт
        # недостающих демо-пользователей под claim-сценарий. Безопасен для
        # уже наполненной облачной БД (Supabase), которую seed_if_empty
        # пропускает по условию «users.count() > 0».
        seed_requests_demo(db)
    finally:
        db.close()
    # Демо-данные тэгов — после seed, когда документы уже созданы.
    apply_sql_migrations(engine, ["003_demo_data.sql"])
    apply_sql_migrations(engine, ["005_drop_unused_tables.sql"])


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
        fp = os.path.join(_dist, full_path)
        if full_path and os.path.isfile(fp):
            return FileResponse(fp)
        index = os.path.join(_dist, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        raise HTTPException(status_code=404)
