"""Роутер подсистемы внутренних заявок (этап 1 жизненного цикла).

Поведение реализует BPMN TO-BE (рис. 1.5):
  POST   /requests                       — создать заявку (опц. сразу эскалировать);
  GET    /requests/mine                  — мои заявки (как автор);
  GET    /requests/inbox                 — входящие отдела (после эскалации);
  GET    /requests/{id}                  — детальная карточка заявки + чат;
  POST   /requests/{id}/claim            — взять заявку в работу (claim);
  POST   /requests/{id}/messages         — отправить сообщение в чат заявки;
  POST   /requests/{id}/close            — закрыть заявку;
  GET    /requests/meta/departments      — список подразделений для UI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    Department,
    Notification,
    Request,
    RequestMessage,
    User,
)
from app.schemas import (
    DepartmentOut,
    NotificationOut,
    NotificationsSummary,
    RequestCreate,
    RequestDetailOut,
    RequestMessageCreate,
    RequestMessageOut,
    RequestOut,
    RequestUserRef,
)
from app.services.escalation import (
    classify_department,
    hide_escalation_notifications,
    notify_department,
)

router = APIRouter(prefix="/requests", tags=["requests"])


# ---------------------------------------------------------------------------
# Сериализация
# ---------------------------------------------------------------------------


def _user_ref(u: User | None) -> RequestUserRef | None:
    if u is None:
        return None
    return RequestUserRef(
        id=u.id,
        full_name=u.full_name,
        role_code=u.role.code if u.role else None,
        department_name=u.department.name if u.department else None,
    )


def _dep_out(d: Department | None) -> DepartmentOut | None:
    if d is None:
        return None
    return DepartmentOut(id=d.id, code=d.code, name=d.name)


def _request_out(req: Request, *, messages_count: int) -> RequestOut:
    return RequestOut(
        id=req.id,
        title=req.title,
        body=req.body,
        status=req.status,
        resolution_kind=req.resolution_kind,
        department=_dep_out(req.department),
        author=_user_ref(req.author),
        assignee=_user_ref(req.assignee),
        chat_session_id=req.chat_session_id,
        rag_query_id=req.rag_query_id,
        created_at=req.created_at,
        escalated_at=req.escalated_at,
        claimed_at=req.claimed_at,
        closed_at=req.closed_at,
        messages_count=messages_count,
    )


def _message_out(m: RequestMessage) -> RequestMessageOut:
    return RequestMessageOut(
        id=m.id,
        author=_user_ref(m.author),
        content=m.content,
        created_at=m.created_at,
    )


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------


@router.get("/meta/departments", response_model=list[DepartmentOut])
def list_departments(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    rows = db.query(Department).order_by(Department.name.asc()).all()
    return [_dep_out(r) for r in rows]


def _resolve_department(db: Session, code: str | None, text: str) -> Department | None:
    """Если код задан явно — берём его; иначе — rule-based по тексту."""
    if code:
        d = db.query(Department).filter(Department.code == code).first()
        if d:
            return d
    cls = classify_department(text)
    return db.query(Department).filter(Department.code == cls.code).first()


@router.post("", response_model=RequestDetailOut, status_code=status.HTTP_201_CREATED)
def create_request(
    body: RequestCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    title = (body.title or body.body.strip().splitlines()[0])[:240].strip() or "Заявка"
    req = Request(
        author_id=user.id,
        title=title,
        body=body.body.strip(),
        status="new",
        chat_session_id=body.session_id,
        rag_query_id=body.rag_query_id,
    )
    db.add(req)
    db.flush()

    if body.escalate:
        dep = _resolve_department(db, body.department_code, body.body)
        if dep is None:
            raise HTTPException(
                status_code=400,
                detail="Не удалось определить отдел для эскалации (нет departments).",
            )
        req.department_target_id = dep.id
        req.status = "escalated"
        req.escalated_at = datetime.utcnow()
        db.flush()
        notify_department(db, request=req, department_id=dep.id)

    db.commit()
    db.refresh(req)
    return _build_detail(db, req, user)


@router.get("/mine", response_model=list[RequestOut])
def my_requests(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    rows = (
        db.query(Request)
        .options(
            selectinload(Request.author).selectinload(User.role),
            selectinload(Request.author).selectinload(User.department),
            selectinload(Request.assignee).selectinload(User.role),
            selectinload(Request.assignee).selectinload(User.department),
            selectinload(Request.department),
        )
        .filter(Request.author_id == user.id)
        .order_by(Request.created_at.desc())
        .limit(200)
        .all()
    )
    return [_request_out(r, messages_count=_count_messages(db, r.id)) for r in rows]


@router.get("/inbox", response_model=list[RequestOut])
def department_inbox(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Заявки моего отдела: ещё не взятые в работу + те, что я взял.

    Логика claim-видимости: после того как кто-то нажал «Взять в работу»,
    заявка пропадает из inbox у всех, кроме самого ``assignee``.
    """
    if not user.department_id:
        return []
    q = (
        db.query(Request)
        .options(
            selectinload(Request.author).selectinload(User.role),
            selectinload(Request.author).selectinload(User.department),
            selectinload(Request.assignee).selectinload(User.role),
            selectinload(Request.assignee).selectinload(User.department),
            selectinload(Request.department),
        )
        .filter(Request.department_target_id == user.department_id)
        .filter(
            (Request.assignee_id.is_(None)) | (Request.assignee_id == user.id)
        )
        .filter(Request.status.in_(("escalated", "in_progress", "closed")))
        .order_by(Request.created_at.desc())
        .limit(200)
    )
    rows = q.all()
    return [_request_out(r, messages_count=_count_messages(db, r.id)) for r in rows]


def _count_messages(db: Session, request_id: int) -> int:
    return (
        db.query(func.count(RequestMessage.id))
        .filter(RequestMessage.request_id == request_id)
        .scalar()
        or 0
    )


def _load_request(db: Session, request_id: int) -> Request:
    req = (
        db.query(Request)
        .options(
            selectinload(Request.author).selectinload(User.role),
            selectinload(Request.author).selectinload(User.department),
            selectinload(Request.assignee).selectinload(User.role),
            selectinload(Request.assignee).selectinload(User.department),
            selectinload(Request.department),
            selectinload(Request.messages)
            .selectinload(RequestMessage.author)
            .selectinload(User.role),
            selectinload(Request.messages)
            .selectinload(RequestMessage.author)
            .selectinload(User.department),
        )
        .filter(Request.id == request_id)
        .first()
    )
    if req is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return req


def _can_view(req: Request, user: User) -> bool:
    if user.role and user.role.code == "admin":
        return True
    if req.author_id == user.id:
        return True
    if req.assignee_id == user.id:
        return True
    if (
        user.department_id
        and req.department_target_id == user.department_id
        and req.status in ("escalated", "in_progress", "closed")
        and (req.assignee_id is None or req.assignee_id == user.id)
    ):
        return True
    return False


def _build_detail(db: Session, req: Request, user: User) -> RequestDetailOut:
    if not _can_view(req, user):
        raise HTTPException(status_code=403, detail="Нет доступа к этой заявке")

    is_author = req.author_id == user.id
    is_assignee = req.assignee_id == user.id
    is_department_member = (
        user.department_id is not None
        and req.department_target_id == user.department_id
    )
    open_statuses = ("escalated", "in_progress")

    can_claim = (
        req.status == "escalated"
        and req.assignee_id is None
        and is_department_member
        and not is_author
    )
    can_close = req.status in open_statuses and (is_assignee or is_author)
    can_reply = req.status in open_statuses and (is_author or is_assignee)

    detail = RequestDetailOut(
        **_request_out(req, messages_count=len(req.messages)).model_dump(),
        messages=[_message_out(m) for m in req.messages],
        can_claim=can_claim,
        can_close=can_close,
        can_reply=can_reply,
    )
    return detail


@router.get("/{request_id}", response_model=RequestDetailOut)
def get_request(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    req = _load_request(db, request_id)
    # автоматически отмечаем как прочитанные «свои» уведомления по этой заявке
    db.query(Notification).filter(
        Notification.recipient_id == user.id,
        Notification.request_id == request_id,
        Notification.is_read.is_(False),
    ).update({Notification.is_read: True})
    db.commit()
    return _build_detail(db, req, user)


@router.post("/{request_id}/claim", response_model=RequestDetailOut)
def claim_request(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    req = _load_request(db, request_id)
    if req.status != "escalated":
        raise HTTPException(status_code=409, detail="Заявка не в статусе «эскалация».")
    if req.assignee_id is not None:
        raise HTTPException(status_code=409, detail="Заявку уже взяли в работу.")
    if not user.department_id or req.department_target_id != user.department_id:
        raise HTTPException(status_code=403, detail="Только сотрудник отдела-получателя может взять заявку.")
    if req.author_id == user.id:
        raise HTTPException(status_code=403, detail="Нельзя взять в работу собственную заявку.")

    req.assignee_id = user.id
    req.claimed_at = datetime.utcnow()
    req.status = "in_progress"
    db.flush()

    hide_escalation_notifications(db, req.id, keep_user_id=user.id)

    # Уведомить автора, что заявку взяли
    db.add(
        Notification(
            recipient_id=req.author_id,
            kind="request_claimed",
            request_id=req.id,
            title=f"Заявка №{req.id} принята в работу",
            body=f"{user.full_name} принял(а) заявку «{req.title}» в работу.",
        )
    )
    db.commit()
    db.refresh(req)
    return _build_detail(db, req, user)


@router.post("/{request_id}/messages", response_model=RequestMessageOut)
def post_message(
    request_id: int,
    body: RequestMessageCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    req = _load_request(db, request_id)
    if req.status not in ("escalated", "in_progress"):
        raise HTTPException(status_code=409, detail="Заявка закрыта; сообщения недоступны.")
    if user.id != req.author_id and user.id != req.assignee_id:
        raise HTTPException(status_code=403, detail="Сообщения могут писать инициатор и исполнитель.")

    msg = RequestMessage(
        request_id=req.id,
        author_id=user.id,
        content=body.content.strip(),
    )
    db.add(msg)
    db.flush()

    # Уведомление другой стороне (если она есть)
    other_id: Optional[int] = None
    if user.id == req.author_id and req.assignee_id:
        other_id = req.assignee_id
    elif user.id == req.assignee_id:
        other_id = req.author_id
    if other_id is not None:
        db.add(
            Notification(
                recipient_id=other_id,
                kind="request_message",
                request_id=req.id,
                title=f"Новое сообщение в заявке №{req.id}",
                body=msg.content[:280] + ("…" if len(msg.content) > 280 else ""),
            )
        )

    db.commit()
    db.refresh(msg)
    return _message_out(msg)


@router.post("/{request_id}/close", response_model=RequestDetailOut)
def close_request(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    req = _load_request(db, request_id)
    if req.status == "closed":
        raise HTTPException(status_code=409, detail="Заявка уже закрыта.")
    if user.id != req.assignee_id and user.id != req.author_id and (
        not user.role or user.role.code != "admin"
    ):
        raise HTTPException(status_code=403, detail="Закрыть может исполнитель, инициатор или администратор.")

    req.status = "closed"
    req.closed_at = datetime.utcnow()
    req.closed_by_id = user.id
    if req.resolution_kind is None:
        req.resolution_kind = "specialist"
    db.flush()

    # Уведомить другую сторону
    other_id: Optional[int] = None
    if user.id == req.author_id and req.assignee_id:
        other_id = req.assignee_id
    elif user.id == req.assignee_id:
        other_id = req.author_id
    if other_id is not None:
        db.add(
            Notification(
                recipient_id=other_id,
                kind="request_closed",
                request_id=req.id,
                title=f"Заявка №{req.id} закрыта",
                body=f"{user.full_name} закрыл(а) заявку «{req.title}».",
            )
        )
    db.commit()
    db.refresh(req)
    return _build_detail(db, req, user)
