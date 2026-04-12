from __future__ import annotations

import json
import re
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Document, User, document_roles
from app.services.embeddings import embed_query
from app.services.llm import generate_rag_answer

# Повторяющиеся вводные абзацы в демо-документах — без совпадения запроса с названием дают ложные попадания
_BOILERPLATE_PREFIXES = (
    "документ определяет обязанности сторон",
    "настоящий документ разработан",
    "работодатель обязан создать условия",
)


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[\wа-яё]+", text.lower(), flags=re.IGNORECASE)
    return {t for t in raw if len(t) >= 3}


def _title_match_score(question: str, title: str) -> float:
    """0..1: доля слов запроса (длина ≥3), встречающихся в названии документа."""
    q, t = _tokens(question), _tokens(title)
    if not q or not t:
        return 0.0
    inter = q & t
    return len(inter) / max(len(q), 1)


def _lexical_in_text(question: str, text: str) -> float:
    """Доля «значимых» слов запроса, встречающихся во фрагменте."""
    q = {w for w in _tokens(question) if len(w) >= 4}
    if not q:
        return 0.0
    blob = text.lower()
    hits = sum(1 for w in q if w in blob)
    return hits / len(q)


def _boilerplate_factor(excerpt: str, title_match: float) -> float:
    """Снижает вес шаблонных вводных, если название документа слабо связано с вопросом."""
    if title_match >= 0.12:
        return 1.0
    head = excerpt.lower().strip()[:120]
    for p in _BOILERPLATE_PREFIXES:
        if head.startswith(p):
            return 0.35
    return 1.0


def _hybrid_score(
    cosine: float,
    question: str,
    title: str,
    excerpt: str,
) -> float:
    tm = _title_match_score(question, title)
    lex = _lexical_in_text(question, excerpt)
    bp = _boilerplate_factor(excerpt, tm)
    # Косинус + явное совпадение с названием и текстом; штраф за «общий» вводный абзац
    return (0.45 * cosine + 0.35 * tm + 0.20 * lex) * bp


def _rank_chunks_by_similarity(
    query: list[float],
    embeddings: list[list[float]],
    *,
    pool: int = 48,
    min_similarity: float = 0.18,
) -> list[tuple[int, float]]:
    """Возвращает (индекс строки в embeddings, косинусное сходство), до `pool` лучших."""
    if not embeddings:
        return []
    q = np.asarray(query, dtype=np.float32)
    q = q / (np.linalg.norm(q) + 1e-9)
    m = np.asarray(embeddings, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    m = m / norms
    sim = m @ q
    order = np.argsort(-sim)[: min(pool, len(sim))]
    ranked = [(int(i), float(sim[i])) for i in order]
    ranked.sort(key=lambda x: -x[1])
    # отсекаем совсем слабый хвост, но оставляем запас для гибридного пересчёта
    filtered = [p for p in ranked if p[1] >= min_similarity]
    if not filtered:
        filtered = ranked[: min(12, len(ranked))]
    return filtered


def retrieve_chunks(
    db: Session,
    user: User,
    question: str,
    top_k: int = 6,
) -> tuple[list[dict[str, Any]], list[float]]:
    settings = get_settings()
    qvec = embed_query(question, settings.embedding_model)

    q_chunks = db.query(Chunk).join(Document, Chunk.document_id == Document.id)
    if user.role.code != "admin":
        q_chunks = q_chunks.join(
            document_roles,
            document_roles.c.document_id == Document.id,
        ).filter(document_roles.c.role_id == user.role_id)

    rows: list[Chunk] = q_chunks.all()
    if not rows:
        return [], []

    doc_ids = {r.document_id for r in rows}
    titles = {
        rid: ttl
        for rid, ttl in db.execute(
            select(Document.id, Document.title).where(Document.id.in_(doc_ids))
        ).all()
    }

    embeddings = [r.embedding for r in rows]
    ranked_cos = _rank_chunks_by_similarity(qvec, embeddings)

    scored: list[tuple[int, float]] = []
    for i, cos in ranked_cos:
        ch = rows[i]
        did = ch.document_id
        title = titles.get(did, "?")
        excerpt = ch.content[:1200]
        hybrid = _hybrid_score(cos, question, title, excerpt)
        scored.append((i, hybrid))

    scored.sort(key=lambda x: -x[1])
    top = scored[:top_k]

    blocks: list[dict[str, Any]] = []
    scores: list[float] = []
    for i, hybrid in top:
        ch = rows[i]
        did = ch.document_id
        blocks.append(
            {
                "title": titles.get(did, "?"),
                "excerpt": ch.content[:1200],
                "doc_id": did,
                "chunk_index": ch.chunk_index,
            }
        )
        scores.append(hybrid)
    return blocks, scores


async def answer_question(db: Session, user: User, question: str) -> tuple[str, list[dict[str, Any]]]:
    blocks, _ = retrieve_chunks(db, user, question, top_k=5)
    sources = [
        {
            "document_id": b["doc_id"],
            "document_title": b["title"],
            "chunk_index": b["chunk_index"],
            "excerpt": b["excerpt"][:400],
        }
        for b in blocks
    ]
    answer = await generate_rag_answer(
        question,
        [{"title": b["title"], "excerpt": b["excerpt"], "doc_id": b["doc_id"], "chunk_index": b["chunk_index"]} for b in blocks],
    )
    return answer, sources


def sources_to_json(sources: list[dict[str, Any]]) -> str:
    return json.dumps(sources, ensure_ascii=False)
