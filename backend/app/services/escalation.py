"""Сервис эскалации внутренней заявки.

Содержит:
  * порог уверенности RAG-ответа (``rag_uncertain`` → надо эскалировать);
  * rule-based классификатор темы заявки → код подразделения;
  * вспомогательные функции рассылки/гашения уведомлений.

Решение по реализации зафиксировано в главе 2 ВКР (см. рис. 1.5 BPMN TO-BE,
рис. 2.x UML Sequence «Эскалация заявки и уведомление отдела»). Намеренно
используется простой rule-based подход (а не LLM-классификатор), чтобы
не зависеть от внешних API и оставаться воспроизводимым на защите.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Notification, Request, User


# Порог гибридной релевантности: ниже — считаем ответ «неуверенным» и
# предлагаем сотруднику передать заявку специалистам.
RAG_UNCERTAIN_THRESHOLD = 0.35

# Маркеры в ответе LLM, говорящие об отсутствии ответа в корпусе.
_NO_DATA_MARKERS = (
    "в корпусе нет данных",
    "в предоставленных фрагментах нет",
    "нет информации",
    "не удалось найти",
    "недостаточно данных",
    "i don't know",
    "i do not know",
)


def is_rag_uncertain(
    top_score: float | None,
    answer_text: str,
    *,
    best_title_match: float | None = None,
) -> bool:
    """True, если ответ RAG нужно считать неуверенным.

    Срабатывает по любому из условий:
      * нет релевантных фрагментов (top_score is None или < THRESHOLD);
      * в тексте ответа LLM есть маркер «не нашли в корпусе».
    """
    if best_title_match is not None and best_title_match >= 0.33:
        if top_score is not None and top_score >= 0.20:
            return False
    if top_score is None or top_score < RAG_UNCERTAIN_THRESHOLD:
        return True
    lo = (answer_text or "").lower()
    return any(m in lo for m in _NO_DATA_MARKERS)


# ---------------------------------------------------------------------------
# Rule-based классификатор темы → код подразделения (departments.code).
# ---------------------------------------------------------------------------
# Ключевые слова приводятся к нижнему регистру и матчатся по подстроке
# в нормализованном (буквы/цифры) тексте заявки.

DEPARTMENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hr": (
        "больничн", "отпуск", "зарплат", "премия", "увольн", "трудов",
        "кадров", "трудоустройств", "отгул", "командиров", "декрет",
        "налог", "ндфл", "справк", "график работ", "табель",
    ),
    "it": (
        "пароль", "учётн", "учетн", "доступ", "vpn", "впн", "1с",
        "1с:", "принтер", "сканер", "офис", "компьютер", "ноутбук",
        "почт", "outlook", "сеть", "wi-fi", "wifi", "монитор",
        "сайт", "програм", "приложен", "сервер", "база данных",
    ),
    "qc": (
        "качеств", "брак", "несоответств", "контрол", "проб",
        "отк", "приём", "испытан", "акт несоответств", "рекламац",
    ),
    "production": (
        "лини", "оборудован", "смена", "наряд", "цех", "резк",
        "перемотк", "печат", "упаковк", "механик", "поломк",
        "технолог", "материал", "сырь",
    ),
    "purchase": (
        "поставщик", "закупк", "снабжен", "заказ материал", "контрагент",
    ),
    "sales": (
        "клиент", "продаж", "договор поставк", "коммерческ",
        "прайс", "тендер", "счёт клиент", "счет клиент",
    ),
    "warehouse": (
        "склад", "отгрузк", "приёмк сырь", "приемк сырь", "хранен",
        "логистик", "транспорт", "паллет", "погруз",
    ),
    "finance": (
        "бухгалтер", "счёт-фактур", "счет-фактур", "акт сверк",
        "командировочн расход", "авансов отчёт", "авансов отчет",
        "оплат", "платёж", "платеж",
    ),
}

# Если ни одно правило не сработало — направляем в ИТ-службу
# (как технический владелец портала EDDA).
FALLBACK_DEPARTMENT_CODE = "it"


@dataclass(frozen=True)
class Classification:
    code: str
    matched_keyword: str | None


def _normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text


def classify_department(text: str) -> Classification:
    """Подбирает код подразделения по ключевым словам в тексте заявки."""
    norm = _normalize(text or "")
    if not norm.strip():
        return Classification(FALLBACK_DEPARTMENT_CODE, None)

    best: tuple[str, str, int] | None = None  # (dept_code, keyword, position)
    for code, words in DEPARTMENT_KEYWORDS.items():
        for w in words:
            wn = w.lower().replace("ё", "е")
            idx = norm.find(wn)
            if idx == -1:
                continue
            if best is None or idx < best[2]:
                best = (code, w, idx)

    if best is None:
        return Classification(FALLBACK_DEPARTMENT_CODE, None)
    return Classification(best[0], best[1])


# ---------------------------------------------------------------------------
# Сервис уведомлений
# ---------------------------------------------------------------------------


def notify_department(
    db: Session,
    *,
    request: Request,
    department_id: int,
    kind: str = "request_escalated",
    title: str | None = None,
    body: str | None = None,
) -> int:
    """Создаёт по одному уведомлению на каждого активного сотрудника
    указанного подразделения (кроме автора заявки).

    Возвращает число фактически созданных уведомлений.
    """
    if not department_id:
        return 0

    recipients = (
        db.query(User)
        .filter(
            User.department_id == department_id,
            User.is_active.is_(True),
            User.id != request.author_id,
        )
        .all()
    )

    if not recipients:
        return 0

    auto_title = title or f"Новая заявка от {request.author.full_name}"
    auto_body = body or (request.body[:280] + ("…" if len(request.body) > 280 else ""))

    created = 0
    for u in recipients:
        db.add(
            Notification(
                recipient_id=u.id,
                kind=kind,
                request_id=request.id,
                title=auto_title,
                body=auto_body,
            )
        )
        created += 1
    db.flush()
    return created


def hide_escalation_notifications(db: Session, request_id: int, keep_user_id: int | None) -> None:
    """Прячет уведомления об эскалации заявки у всех получателей, кроме
    указанного пользователя (если задан). Используется после claim.
    """
    q = db.query(Notification).filter(
        Notification.request_id == request_id,
        Notification.kind == "request_escalated",
        Notification.is_hidden.is_(False),
    )
    if keep_user_id is not None:
        q = q.filter(Notification.recipient_id != keep_user_id)
    for n in q.all():
        n.is_hidden = True
    db.flush()
