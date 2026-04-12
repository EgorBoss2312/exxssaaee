from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Role, User
from app.schemas import LlmStatusOut, RoleOut

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/roles", response_model=list[RoleOut])
def list_roles_for_ui(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Список ролей для форм (загрузка документов, отображение)."""
    return db.query(Role).order_by(Role.id.asc()).all()


@router.get("/llm", response_model=LlmStatusOut)
def llm_status(_: Annotated[User, Depends(get_current_user)]) -> LlmStatusOut:
    """
    Показывает, будет ли ответ собираться языковой моделью или только фрагментами (extractive).
    Не проверяет валидность API-ключей — только их наличие и доступность Ollama по HTTP.
    """
    settings = get_settings()
    if settings.gemini_api_key:
        return LlmStatusOut(mode="gemini", model=settings.gemini_model)
    if settings.openai_api_key:
        return LlmStatusOut(mode="openai", model=settings.openai_model)
    base = settings.ollama_base_url.rstrip("/")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=2.0)
        if r.status_code == 200:
            return LlmStatusOut(mode="ollama", model=settings.ollama_model)
    except Exception:
        pass
    return LlmStatusOut(
        mode="extractive",
        hint=(
            "Локально: в backend/.env задайте GEMINI_API_KEY или OPENAI_API_KEY и перезапустите сервер. "
            "На Render/Railway: Environment → добавьте ту же переменную (без кавычек), redeploy. "
            f"Либо Ollama по адресу {base} и ollama pull {settings.ollama_model}"
        ),
    )
