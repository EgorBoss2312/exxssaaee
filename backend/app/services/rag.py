from __future__ import annotations

import json
import re
import time
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

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
    # Сильнее учитываем совпадение с названием документа (важно при hash-эмбеддингах)
    return (0.30 * cosine + 0.50 * tm + 0.20 * lex) * bp


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


def _doc_title_scores(question: str, titles: dict[int, str]) -> dict[int, float]:
    return {did: _title_match_score(question, title) for did, title in titles.items()}


def _focus_context_blocks(
    question: str,
    blocks: list[dict[str, Any]],
    *,
    min_title_match: float = 0.28,
) -> list[dict[str, Any]]:
    """Если вопрос явно про конкретный документ — оставляем фрагменты только из него."""
    if not blocks:
        return blocks
    scored = [(b, _title_match_score(question, b["title"])) for b in blocks]
    best = max(score for _, score in scored)
    if best < min_title_match:
        return blocks
    focused = [b for b, score in scored if score >= best - 0.08]
    return focused or blocks


def _llm_denies_answer(text: str) -> bool:
    lo = (text or "").lower()
    markers = (
        "не содержат",
        "не содержит",
        "нет информации",
        "недостаточно",
        "не найдено",
        "очень мало информации",
        "единственный фрагмент",
        "в предоставленных фрагментах",
        "в корпусе нет",
    )
    return any(m in lo for m in markers)


def _extractive_answer(question: str, blocks: list[dict[str, Any]]) -> str:
    """Связный ответ из найденных фрагментов без LLM (если модель «отказалась»)."""
    if not blocks:
        return (
            "По вашему запросу не найдено релевантных фрагментов в базе знаний, доступной для вашей роли."
        )
    focused = _focus_context_blocks(question, blocks)
    title = focused[0]["title"]
    parts: list[str] = [
        f"По документу «{title}» в базе знаний доступна следующая информация:",
        "",
    ]
    seen: set[str] = set()
    for b in focused[:5]:
        text = re.sub(r"\s+", " ", (b["excerpt"] or "").strip())
        if len(text) < 40:
            continue
        key = text[:160]
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"• {text[:700]}")
    if len(parts) <= 2:
        parts.append("• " + (focused[0]["excerpt"] or "")[:900])
    parts.append("")
    parts.append(f"Источник: {title}.")
    return "\n".join(parts)


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
    title_by_doc = _doc_title_scores(question, titles)
    best_doc_match = max(title_by_doc.values(), default=0.0)

    embeddings = [r.embedding for r in rows]
    ranked_cos = _rank_chunks_by_similarity(qvec, embeddings)

    scored: list[tuple[int, float]] = []
    for i, cos in ranked_cos:
        ch = rows[i]
        did = ch.document_id
        title = titles.get(did, "?")
        excerpt = ch.content[:1200]
        hybrid = _hybrid_score(cos, question, title, excerpt)
        doc_tm = title_by_doc.get(did, 0.0)
        if best_doc_match >= 0.25:
            if doc_tm >= best_doc_match - 0.06:
                hybrid += 0.25 + 0.35 * doc_tm
            elif doc_tm < 0.10:
                hybrid *= 0.45
        scored.append((i, hybrid))

    # Явный запрос по названию: поднимаем содержательные фрагменты целевого документа
    if best_doc_match >= 0.28:
        best_doc_ids = [
            did for did, tm in title_by_doc.items() if tm >= best_doc_match - 0.08
        ][:2]
        boosted: list[tuple[int, float]] = []
        for did in best_doc_ids:
            doc_rows = [(idx, rows[idx]) for idx in range(len(rows)) if rows[idx].document_id == did]
            doc_rows.sort(key=lambda x: x[1].chunk_index)
            for idx, ch in doc_rows[:6]:
                tm = title_by_doc.get(did, 0.0)
                lex = _lexical_in_text(question, ch.content)
                boosted.append((idx, 0.55 + 0.30 * tm + 0.15 * lex))
        seen_idx: set[int] = set()
        merged: list[tuple[int, float]] = []
        for idx, sc in sorted(boosted, key=lambda x: -x[1]):
            if idx in seen_idx:
                continue
            seen_idx.add(idx)
            merged.append((idx, sc))
        for idx, sc in sorted(scored, key=lambda x: -x[1]):
            if idx in seen_idx:
                continue
            seen_idx.add(idx)
            merged.append((idx, sc))
        scored = merged

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
                "chunk_id": ch.id,
                "chunk_index": ch.chunk_index,
            }
        )
        scores.append(hybrid)
    return blocks, scores


def _detect_llm_provider(settings) -> str:
    """Определяет, какой провайдер LLM фактически активен (по приоритету в llm.py)."""
    if (settings.gemini_api_key or "").strip():
        return "gemini"
    if (settings.openai_api_key or "").strip():
        return "openai"
    if (settings.ollama_base_url or "").strip():
        return "ollama"
    return "extractive"


def find_inaccessible_matching_documents(
    db: Session,
    user: User,
    question: str,
    *,
    min_title_match: float = 0.28,
) -> list[str]:
    """Документы, чьё название совпадает с вопросом, но недоступны по роли пользователя."""
    if user.role.code == "admin":
        return []
    rows = db.query(Document).options(joinedload(Document.allowed_roles)).all()
    blocked: list[str] = []
    for doc in rows:
        if _title_match_score(question, doc.title) < min_title_match:
            continue
        allowed = {r.id for r in doc.allowed_roles}
        if user.role_id not in allowed:
            blocked.append(doc.title)
    return blocked


async def answer_question(
    db: Session, user: User, question: str, *, top_k: int = 5
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Возвращает (answer, sources_for_response, meta_for_journal).

    meta_for_journal содержит данные для журналирования в rag_queries / query_sources:
        - chunks_used: list[{chunk_id, score, rank, document_id}]
        - top_k, latency_ms, used_llm, llm_provider, llm_model, embedding_model_code
    """
    settings = get_settings()
    started = time.monotonic()

    blocks, scores = retrieve_chunks(db, user, question, top_k=top_k)

    blocked_titles = find_inaccessible_matching_documents(db, user, question)
    best_title_match = max(
        (_title_match_score(question, b["title"]) for b in blocks),
        default=0.0,
    )

    llm_blocks = _focus_context_blocks(question, blocks)

    sources = [
        {
            "document_id": b["doc_id"],
            "document_title": b["title"],
            "chunk_index": b["chunk_index"],
            "excerpt": b["excerpt"][:400],
        }
        for b in blocks
    ]

    provider = _detect_llm_provider(settings)
    llm_model = {
        "gemini": settings.gemini_model,
        "openai": settings.openai_model,
        "ollama": settings.ollama_model,
        "extractive": None,
    }.get(provider)

    answer = await generate_rag_answer(
        question,
        [{"title": b["title"], "excerpt": b["excerpt"],
          "doc_id": b["doc_id"], "chunk_index": b["chunk_index"]}
         for b in llm_blocks],
    )

    if _llm_denies_answer(answer) and best_title_match >= 0.25 and llm_blocks:
        answer = _extractive_answer(question, llm_blocks)

    if blocked_titles and best_title_match < 0.28:
        blocked_hint = (
            f"В базе знаний есть документ «{blocked_titles[0]}», но он недоступен для вашей роли "
            f"({user.role.name}). Обратитесь в отдел кадров или к администратору портала."
        )
        if "не найдено" in answer.lower() or "не содержат" in answer.lower() or "недостаточно" in answer.lower():
            answer = blocked_hint
        else:
            answer = f"{blocked_hint}\n\n{answer}"

    latency_ms = int((time.monotonic() - started) * 1000)

    chunks_used = [
        {
            "chunk_id": b["chunk_id"],
            "document_id": b["doc_id"],
            "rank": rank + 1,
            "score": float(scores[rank]) if rank < len(scores) else None,
        }
        for rank, b in enumerate(blocks)
    ]

    top_score = float(max(scores)) if scores else None

    meta = {
        "chunks_used": chunks_used,
        "top_k": top_k,
        "latency_ms": latency_ms,
        "used_llm": provider != "extractive",
        "llm_provider": provider,
        "llm_model": llm_model,
        "embedding_model_code": settings.embedding_model,
        "top_score": top_score,
        "best_title_match": best_title_match,
    }

    return answer, sources, meta


def sources_to_json(sources: list[dict[str, Any]]) -> str:
    return json.dumps(sources, ensure_ascii=False)
