import os
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
# Корень backend (в Docker WORKDIR это /app) — для относительных путей к uploads
BACKEND_ROOT = _BACKEND_ROOT
_ENV_FILE = _BACKEND_ROOT / ".env"
# Локальная разработка: совпадает с `docker compose up` (сервис db на порту 5432).
# На PaaS задайте DATABASE_URL из панели (managed PostgreSQL).
_DEFAULT_POSTGRES = "postgresql+psycopg://edda:edda@127.0.0.1:5432/edda"


def _origins_from_paas_env() -> list[str]:
    """Публичный URL сервиса на Render/Railway/Fly — чтобы CORS не ломался без ручного .env."""
    out: list[str] = []
    render = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if render:
        out.append(render.rstrip("/"))
    railway = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if railway:
        if railway.startswith("http"):
            out.append(railway.rstrip("/"))
        else:
            out.append(f"https://{railway.lstrip('/')}")
    rail_url = os.environ.get("RAILWAY_STATIC_URL", "").strip()
    if rail_url:
        out.append(rail_url.rstrip("/"))
    fly = os.environ.get("FLY_APP_NAME", "").strip()
    if fly:
        out.append(f"https://{fly}.fly.dev")
    manual = os.environ.get("PUBLIC_SITE_URL", "").strip()
    if manual:
        out.append(manual.rstrip("/"))
    return out


class Settings(BaseSettings):
    # PostgreSQL (драйвер psycopg v3). Переопределение через DATABASE_URL.
    database_url: str = _DEFAULT_POSTGRES
    jwt_secret: str = "change-me-in-production-use-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    allow_registration: bool = False
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    upload_dir: str = "data/uploads"
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )
    # Опционально: один regex на Origin (например превью *.vercel.app). См. Starlette CORSMiddleware.allow_origin_regex
    cors_origin_regex: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        # Пустые значения переменных окружения не подставляются как ""
        env_ignore_empty=True,
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, v: object) -> object:
        """Render/Supabase часто отдают postgresql:// или postgres://; драйвер в проекте — psycopg v3."""
        if not isinstance(v, str):
            return v
        s = v.strip()
        if not s or "://" not in s:
            return v
        scheme, rest = s.split("://", 1)
        if "+" in scheme:
            return s
        low = scheme.lower()
        if low == "postgres":
            return f"postgresql+psycopg://{rest}"
        if low == "postgresql":
            return f"postgresql+psycopg://{rest}"
        return s

    @field_validator("cors_origin_regex", mode="before")
    @classmethod
    def _cors_regex_empty(cls, v: object) -> Optional[str]:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return None

    @field_validator("openai_api_key", "gemini_api_key", mode="before")
    @classmethod
    def _strip_api_keys(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        xs = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        # Пустой список из ошибки в .env ломает CORS для всех; возвращаем дефолт разработки
        if not xs:
            xs = [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
            ]
        extra = _origins_from_paas_env()
        return list(dict.fromkeys([*xs, *extra]))


def get_settings() -> Settings:
    """Без lru_cache: после сохранения backend/.env достаточно перезагрузить страницу (новый запрос прочитает файл)."""
    return Settings()
