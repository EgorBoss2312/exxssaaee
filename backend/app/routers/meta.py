import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.llm import probe_gemini
from app.database import get_db
from app.deps import get_current_user
from app.models import DocumentTag, Role, User
from app.schemas import DocumentTagOut, LlmStatusOut, RoleOut

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/roles", response_model=list[RoleOut])
def list_roles_for_ui(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Список ролей для форм (загрузка документов, отображение)."""
    return db.query(Role).order_by(Role.id.asc()).all()


@router.get("/document-tags", response_model=list[DocumentTagOut])
def list_document_tags_for_ui(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Справочник тегов документов для формы загрузки и отображения."""
    return db.query(DocumentTag).order_by(DocumentTag.name.asc()).all()


@router.get("/llm", response_model=LlmStatusOut)
async def llm_status(_: Annotated[User, Depends(get_current_user)]) -> LlmStatusOut:
    """
    Показывает активный режим LLM. Для Gemini дополнительно проверяет, отвечает ли API.
    """
    settings = get_settings()
    if settings.gemini_api_key:
        probe = await probe_gemini(settings)
        if probe["ok"]:
            return LlmStatusOut(mode="gemini", model=settings.gemini_model)
        return LlmStatusOut(
            mode="extractive",
            hint=(
                f"Ключ Gemini задан, но Google API не отвечает: {probe['detail']}. "
                "Render → Environment → проверьте GEMINI_API_KEY (без кавычек) → Manual Deploy."
            ),
        )
    if settings.openai_api_key:
        return LlmStatusOut(mode="openai", model=settings.openai_model)
    base = settings.ollama_base_url.rstrip("/")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=2.0)
        if r.status_code == 200:
            return LlmStatusOut(mode="ollama", model=settings.ollama_model)
    except Exception:
        pass
    return LlmStatusOut(mode="extractive", hint=_extractive_hint(settings, base))


def _extractive_hint(settings, ollama_base: str) -> str:
    """Короткая подсказка для UI; детали — в README."""
    if os.environ.get("RENDER", "").strip():
        return (
            "Связный ответ: в Render → Environment добавьте GEMINI_API_KEY или OPENAI_API_KEY (без кавычек) → Save → Deploy."
        )
    if os.environ.get("RAILWAY_ENVIRONMENT", "").strip() or os.environ.get("RAILWAY_PROJECT_ID", "").strip():
        return (
            "Связный ответ: в Railway → Variables задайте GEMINI_API_KEY или OPENAI_API_KEY → redeploy."
        )
    return (
        "Связный ответ: в backend/.env укажите GEMINI_API_KEY или OPENAI_API_KEY и перезапустите сервер; "
        f"либо Ollama ({ollama_base}) и модель «{settings.ollama_model}». Подробнее — README."
    )
