from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    ChatMessage,
    ChatSession,
    EmbeddingModel,
    QueryFeedback,
    QuerySource,
    RagQuery,
    User,
)
from app.schemas import (
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
    ChatSessionOut,
    FeedbackRequest,
    SourceRef,
)
from app.models import Department
from app.services.escalation import classify_department, is_rag_uncertain
from app.services.rag import answer_question, sources_to_json

router = APIRouter(prefix="/chat", tags=["chat"])


def _resolve_embedding_model_id(db: Session, code: str | None) -> int | None:
    if not code:
        return None
    em = db.query(EmbeddingModel).filter(EmbeddingModel.code == code).first()
    return em.id if em else None


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
    s = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .first()
    )
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
        session = (
            db.query(ChatSession)
            .filter(ChatSession.id == body.session_id, ChatSession.user_id == user.id)
            .first()
        )
    if session is None:
        title = body.message.strip()[:80] + ("…" if len(body.message) > 80 else "")
        session = ChatSession(user_id=user.id, title=title)
        db.add(session)
        db.flush()

    user_msg = ChatMessage(session_id=session.id, role="user", content=body.message)
    db.add(user_msg)
    db.flush()

    answer, sources_raw, meta = await answer_question(db, user, body.message)
    sources = [SourceRef(**s) for s in sources_raw]

    asst = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=answer,
        sources_json=sources_to_json(sources_raw),
    )
    db.add(asst)
    db.flush()

    # --- журналирование RAG-запроса (расширенная модель, миграция 002)
    rag_q = RagQuery(
        user_id=user.id,
        session_id=session.id,
        message_id=asst.id,
        query_text=body.message,
        answer_text=answer,
        top_k=meta["top_k"],
        used_llm=meta["used_llm"],
        llm_provider=meta["llm_provider"],
        llm_model=meta["llm_model"],
        embedding_model_id=_resolve_embedding_model_id(db, meta["embedding_model_code"]),
        latency_ms=meta["latency_ms"],
    )
    db.add(rag_q)
    db.flush()

    for ch in meta["chunks_used"]:
        db.add(
            QuerySource(
                rag_query_id=rag_q.id,
                chunk_id=ch["chunk_id"],
                rank=ch["rank"],
                score=ch["score"],
            )
        )

    db.commit()

    # Решение об эскалации: если RAG неуверенный, подсказываем фронту
    # отдел, в который имеет смысл передать заявку (rule-based).
    uncertain = is_rag_uncertain(
        meta.get("top_score"),
        answer,
        best_title_match=meta.get("best_title_match"),
    )
    suggested_code: str | None = None
    suggested_name: str | None = None
    if uncertain:
        cls = classify_department(body.message)
        suggested_code = cls.code
        dep = db.query(Department).filter(Department.code == cls.code).first()
        suggested_name = dep.name if dep else cls.code

    return ChatResponse(
        answer=answer,
        sources=sources,
        session_id=session.id,
        rag_query_id=rag_q.id,
        rag_uncertain=uncertain,
        top_score=meta.get("top_score"),
        suggested_department_code=suggested_code,
        suggested_department_name=suggested_name,
    )


@router.post("/feedback")
def submit_feedback(
    body: FeedbackRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Принимает обратную связь по конкретному RAG-ответу (тaблица query_feedback).

    Используется на фронтенде кнопками «полезно/не полезно» под ответом.
    """
    rq = db.query(RagQuery).filter(RagQuery.id == body.rag_query_id).first()
    if not rq:
        raise HTTPException(status_code=404, detail="RAG-запрос не найден")
    if rq.user_id and rq.user_id != user.id:
        raise HTTPException(status_code=403, detail="Можно оценивать только собственные запросы")

    fb = QueryFeedback(
        rag_query_id=rq.id,
        user_id=user.id,
        is_helpful=body.is_helpful,
        comment=(body.comment or "").strip() or None,
    )
    db.add(fb)
    db.commit()
    return {"ok": True, "feedback_id": fb.id}
