from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _gemini_model_candidates(primary: str) -> list[str]:
    """Имена моделей по убыванию приоритета; при 404/429 пробуем следующие (актуальные id см. https://ai.google.dev/gemini-api/docs/models)."""
    fallbacks = [
        primary.strip(),
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-flash-latest",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for m in fallbacks:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


async def _gemini_generate(settings: Settings, system: str, user_text: str) -> str | None:
    """REST API Gemini: https://ai.google.dev/api/rest/v1beta/models.generateContent"""
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": 0.2},
    }
    last_body = ""
    last_code = 0
    async with httpx.AsyncClient(timeout=120.0) as client:
        for model in _gemini_model_candidates(settings.gemini_model):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            r = await client.post(
                url,
                params={"key": settings.gemini_api_key},
                json=payload,
            )
            last_code = r.status_code
            last_body = r.text
            if r.status_code in (401, 403):
                logger.warning("Gemini: ключ API отклонён (HTTP %s). Проверьте GEMINI_API_KEY.", r.status_code)
                return None
            if r.status_code == 200:
                data = r.json()
                cands = data.get("candidates") or []
                if not cands:
                    logger.warning("Gemini модель %s: нет candidates: %s", model, str(data)[:800])
                    continue
                parts = (cands[0].get("content") or {}).get("parts") or []
                texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
                out = "\n".join(texts).strip()
                if out:
                    if model != settings.gemini_model.strip():
                        logger.info("Gemini: использована запасная модель %s (основная %s недоступна)", model, settings.gemini_model)
                    else:
                        logger.info("Gemini: ответ получен, модель %s", model)
                    return out
                continue
            logger.warning(
                "Gemini модель %s HTTP %s: %s",
                model,
                r.status_code,
                r.text[:600],
            )
            continue
    logger.warning("Gemini: все модели исчерпаны, последний ответ HTTP %s: %s", last_code, last_body[:1200])
    return None


async def generate_rag_answer(
    question: str,
    context_blocks: list[dict[str, Any]],
) -> str:
    """
    context_blocks: [{"title": str, "excerpt": str, "doc_id": int, "chunk_index": int}, ...]
    """
    settings = get_settings()
    system = (
        "Ты корпоративный ассистент по внутренним документам. Отвечай только на основе предоставленных фрагментов; "
        "если данных недостаточно — так и напиши. Пиши по-русски.\n"
        "Если пользователь ссылается на конкретный документ (по названию или теме), в первую очередь используй фрагменты "
        "с совпадающим или близким названием источника; не подставляй общие вводные абзацы из других документов.\n"
        "Формат ответа: сначала краткий связный пересказ (2–6 предложений), затем при необходимости нумерованные шаги или подпункты. "
        "Не копируй длинные цитаты подряд — переформулируй по сути. Игнорируй фрагменты, явно не относящиеся к вопросу. "
        "В конце можно указать документы-источники по названиям."
    )
    ctx_lines = []
    for i, b in enumerate(context_blocks, 1):
        ctx_lines.append(f"[{i}] Источник: {b['title']}\n{b['excerpt']}")
    user = f"Вопрос: {question}\n\nФрагменты:\n" + "\n\n".join(ctx_lines)

    # Google Gemini (приоритет, если задан GEMINI_API_KEY)
    if settings.gemini_api_key:
        try:
            text = await _gemini_generate(settings, system, user)
            if text:
                return text
        except Exception as e:
            logger.warning("Gemini недоступен или ошибка API: %s", e)

    if settings.openai_api_key:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url or None,
            )
            r = await client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
            )
            return (r.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning("OpenAI недоступен или ошибка API: %s", e)

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                },
            )
            if r.status_code == 200:
                data = r.json()
                msg = data.get("message") or {}
                content = msg.get("content")
                if content:
                    return content.strip()
            logger.warning("Ollama ответила %s: %s", r.status_code, r.text[:500])
    except Exception as e:
        logger.warning("Ollama недоступна: %s", e)

    # Extractive fallback (нет рабочего GEMINI / OpenAI / Ollama)
    if not context_blocks:
        return (
            "По вашему запросу не найдено релевантных фрагментов в базе знаний, доступной для вашей роли. "
            "Уточните формулировку или обратитесь к администратору для добавления документов."
        )
    hint = (
        "\n\n— Связный пересказ даёт языковая модель: задайте в backend/.env переменную GEMINI_API_KEY, "
        "OPENAI_API_KEY или запустите Ollama (см. README проекта). Показаны извлечённые фрагменты.\n"
    )
    parts = []
    for j, b in enumerate(context_blocks[:4], 1):
        parts.append(f"**[{j}] {b['title']}**\n{b['excerpt'][:900]}")
    return (
        "Сейчас активен режим без внешней языковой модели (ключи API не заданы или недоступны). "
        "Ниже — отобранные по запросу фрагменты в порядке релевантности:"
        + hint
        + "\n\n"
        + "\n\n".join(parts)
    )
