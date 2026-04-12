from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth_core import decode_token
from app.database import get_db
from app.models import Role, User

security = HTTPBearer(auto_error=False)


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не авторизован")
    payload = decode_token(creds.credentials)
    if not payload or "uid" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный токен")
    user = db.query(User).filter(User.id == payload["uid"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    role = user.role
    if role.code != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Требуется роль администратора")
    return user


def require_kb_manager(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Администратор или ИТ могут загружать документы."""
    code = user.role.code
    if code not in ("admin", "it"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав для загрузки документов")
    return user
