from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import ChatMessage, ChatSession, User
from app.schemas import ChatMessageOut, ChatRequest, ChatResponse, ChatSessionOut, SourceRef
from app.services.rag import answer_question, sources_to_json

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/sessions", response_model=list[ChatSessionOut])
def list_sessions(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    rows = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.created_at.desc())
        .limit(50)
        .all()
    )
    return rows


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def session_messages(
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    s = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == user.id).first()
    if not s:
        return []
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    session: ChatSession | None = None
    if body.session_id:
        session = db.query(ChatSession).filter(ChatSession.id == body.session_id, ChatSession.user_id == user.id).first()
    if session is None:
        title = body.message.strip()[:80] + ("…" if len(body.message) > 80 else "")
        session = ChatSession(user_id=user.id, title=title)
        db.add(session)
        db.flush()

    user_msg = ChatMessage(session_id=session.id, role="user", content=body.message)
    db.add(user_msg)
    db.flush()

    answer, sources_raw = await answer_question(db, user, body.message)
    sources = [SourceRef(**s) for s in sources_raw]

    asst = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=answer,
        sources_json=sources_to_json(sources_raw),
    )
    db.add(asst)
    db.commit()

    return ChatResponse(answer=answer, sources=sources, session_id=session.id)
