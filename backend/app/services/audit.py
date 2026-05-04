"""Лёгкий хелпер записи в audit_log (миграция 002).

Назначение — журналирование значимых действий пользователей для раздела 2.4
«Обеспечение информационной безопасности» ВКР. Запись делается best-effort:
ошибка журналирования не должна ломать основное действие, поэтому исключения
ловятся и логируются.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog

_log = logging.getLogger(__name__)


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[0].strip() or None
    client = request.client
    return client.host if client else None


def _user_agent(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    return (request.headers.get("user-agent") or "")[:512] or None


def write_audit(
    db: Session,
    *,
    actor_id: Optional[int],
    action: str,
    object_type: Optional[str] = None,
    object_id: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
    commit: bool = False,
) -> None:
    """Создаёт запись audit_log.

    Если ``commit=False`` — оставляет коммит на ответственность вызвавшего кода
    (обычно audit добавляется в общую транзакцию основной операции).
    """
    try:
        entry = AuditLog(
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            details=details,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
        db.add(entry)
        if commit:
            db.commit()
    except Exception as exc:  # pragma: no cover — audit не должен ломать основное действие
        _log.warning("audit_log: failed to write entry (%s): %s", action, exc)
        try:
            db.rollback()
        except Exception:
            pass
