"""Роутер уведомлений (in-app колокольчик)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Notification, User
from app.schemas import NotificationOut, NotificationsSummary

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        kind=n.kind,
        title=n.title,
        body=n.body,
        request_id=n.request_id,
        is_read=n.is_read,
        created_at=n.created_at,
    )


@router.get("", response_model=NotificationsSummary)
def list_notifications(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = 30,
):
    q = (
        db.query(Notification)
        .filter(
            Notification.recipient_id == user.id,
            Notification.is_hidden.is_(False),
        )
        .order_by(Notification.created_at.desc())
    )
    items = q.limit(max(1, min(limit, 100))).all()
    unread = (
        db.query(Notification)
        .filter(
            Notification.recipient_id == user.id,
            Notification.is_hidden.is_(False),
            Notification.is_read.is_(False),
        )
        .count()
    )
    return NotificationsSummary(unread=unread, items=[_to_out(n) for n in items])


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    n = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.recipient_id == user.id,
        )
        .first()
    )
    if n is None:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    if not n.is_read:
        n.is_read = True
        db.commit()
        db.refresh(n)
    return _to_out(n)


@router.post("/read-all")
def mark_all_read(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    db.query(Notification).filter(
        Notification.recipient_id == user.id,
        Notification.is_read.is_(False),
        Notification.is_hidden.is_(False),
    ).update({Notification.is_read: True})
    db.commit()
    return {"ok": True}
