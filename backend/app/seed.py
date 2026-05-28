from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_core import hash_password
from app.config import BACKEND_ROOT, get_settings
from app.storage_paths import normalize_storage_path
from app.models import Department, Document, Role, User
from app.services.ingest import attach_roles, reindex_document


ROLES = [
    ("admin", "Администратор", "Полный доступ к системе и всей документации"),
    ("director", "Руководство", "Стратегические и организационные документы"),
    ("hr", "Отдел кадров", "Кадровые положения, приказы, ОТ и ТБ (общий контур)"),
    ("production", "Производство", "Технологические инструкции, производственные регламенты"),
    ("otk", "ОТК", "Стандарты качества, методики контроля, рекламации"),
    ("it", "ИТ-служба", "Инфраструктура, доступы, сопровождение ИС"),
    ("sales", "Продажи", "Коммерческие регламенты, спецификации для клиентов"),
    ("logistics", "Склад и логистика", "Складские и транспортные процедуры"),
    ("finance", "Финансы и бухгалтерия", "Финансовые политики и учётные регламенты"),
]


def ensure_roles(db: Session) -> dict[str, int]:
    code_to_id: dict[str, int] = {}
    for code, name, desc in ROLES:
        r = db.query(Role).filter(Role.code == code).first()
        if not r:
            r = Role(code=code, name=name, description=desc)
            db.add(r)
            db.flush()
        code_to_id[code] = r.id
    return code_to_id


_ROLE_TO_DEPARTMENT: dict[str, str] = {
    # роль (roles.code) → отдел-приёмник заявок (departments.code, миграция 002)
    "hr": "hr",
    "it": "it",
    "otk": "qc",
    "production": "production",
    "sales": "sales",
    "logistics": "warehouse",
    "finance": "finance",
    "director": "admin",
}


def _dept_id(db: Session, code: str) -> int | None:
    """Возвращает ID подразделения по его коду (если миграция 002 применена)."""
    try:
        d = db.query(Department).filter(Department.code == code).first()
        return d.id if d else None
    except Exception:  # таблица departments ещё не создана (на ранней инициализации)
        return None


# Список демо-пользователей для подсистемы заявок (claim-сценарий).
# Применяется идемпотентно при каждом старте — даже если БД (например, Supabase)
# уже не пустая и обычный seed_if_empty пропускает.
_REQUESTS_DEMO_USERS: list[tuple[str, str, str, str]] = [
    # email, password, full_name, role_code
    ("employee@edda.local", "User123456!", "Петров А.И.",   "production"),
    ("hr2@edda.local",      "Hr223456!",   "Морозова Е.К.", "hr"),
    ("it2@edda.local",      "It223456!",   "Кузнецов А.Н.", "it"),
]


def seed_requests_demo(db: Session) -> None:
    """Идемпотентный «add-on seed» для подсистемы внутренних заявок.

    Безопасен для облачной БД (Supabase) с уже наполненными таблицами:
      1) у существующих пользователей с известным ``role_code`` и пустым
         ``department_id`` проставляет соответствующий отдел по
         ``_ROLE_TO_DEPARTMENT`` (нужно, чтобы было кому слать уведомления
         при эскалации заявки);
      2) досоздаёт недостающих демо-пользователей (``employee@edda.local``,
         ``hr2@edda.local``, ``it2@edda.local``) — без них не получится
         продемонстрировать claim-сценарий (второй сотрудник отдела не видит
         «занятой» заявки).
    """
    try:
        roles = {r.code: r.id for r in db.query(Role).all()}
    except Exception:
        return

    # (1) Backfill department_id для существующих пользователей
    role_id_to_code: dict[int, str] = {rid: code for code, rid in roles.items()}
    updated_dept = 0
    for u in db.query(User).filter(User.department_id.is_(None)).all():
        code = role_id_to_code.get(u.role_id)
        if not code:
            continue
        dep_code = _ROLE_TO_DEPARTMENT.get(code)
        if not dep_code:
            continue
        dep_id = _dept_id(db, dep_code)
        if dep_id is not None:
            u.department_id = dep_id
            updated_dept += 1
    if updated_dept:
        _log.info("seed_requests_demo: backfilled department_id for %d users", updated_dept)

    # (2) Досоздание демо-пользователей (если их ещё нет)
    created = 0
    for email, pw, name, role_code in _REQUESTS_DEMO_USERS:
        if role_code not in roles:
            continue
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            # Идемпотентно проставим department_id, если он пуст
            if existing.department_id is None:
                dep_code = _ROLE_TO_DEPARTMENT.get(role_code)
                if dep_code:
                    dep_id = _dept_id(db, dep_code)
                    if dep_id is not None:
                        existing.department_id = dep_id
            continue
        dep_code = _ROLE_TO_DEPARTMENT.get(role_code)
        dep_id = _dept_id(db, dep_code) if dep_code else None
        db.add(
            User(
                email=email,
                hashed_password=hash_password(pw),
                full_name=name,
                role_id=roles[role_code],
                department_id=dep_id,
                is_active=True,
            )
        )
        created += 1
    if created:
        _log.info("seed_requests_demo: created %d demo users", created)

    if updated_dept or created:
        db.commit()


def seed_if_empty(db: Session) -> None:
    if db.query(User).count() > 0:
        return

    settings = get_settings()
    roles = ensure_roles(db)

    admin = User(
        email="admin@edda.local",
        hashed_password=hash_password(os.environ.get("SEED_ADMIN_PASSWORD", "Admin123!")),
        full_name="Администратор системы",
        role_id=roles["admin"],
        is_active=True,
    )
    db.add(admin)
    db.flush()
    admin_id = admin.id

    # Базовые «исторические» демо-пользователи. Дополнительные демо для
    # подсистемы заявок (employee, второй HR, второй ИТ) досоздаются
    # идемпотентно функцией seed_requests_demo() — это работает и для
    # уже наполненной облачной БД (Supabase).
    demos_data = [
        ("director@edda.local", "Director123!", "Иванов И.И.", "director"),
        ("hr@edda.local",       "Hr123456!",     "Петрова А.С.", "hr"),
        ("prod@edda.local",     "Prod123456!",   "Сидоров П.П.", "production"),
        ("otk@edda.local",      "Otk123456!",    "Козлова Е.В.", "otk"),
        ("it@edda.local",       "It123456!",     "Смирнов Д.Д.", "it"),
    ]
    for email, pw, name, code in demos_data:
        dep_code = _ROLE_TO_DEPARTMENT.get(code)
        db.add(
            User(
                email=email,
                hashed_password=hash_password(pw),
                full_name=name,
                role_id=roles[code],
                department_id=_dept_id(db, dep_code) if dep_code else None,
                is_active=True,
            )
        )
    db.commit()

    # Sample knowledge files
    kb_dir = Path(__file__).resolve().parent.parent / "seed_kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    samples = [
        (
            "Регламент информационной безопасности",
            "it_security.txt",
            """Регламент информационной безопасности ООО «ЭДДА»

1. Учётные записи выдаются только через заявку в ИТ-службу.
2. Пароли меняются не реже одного раза в 90 дней.
3. Запрещена передача учётных данных третьим лицам.
4. Доступ к производственной сети осуществляется только с утверждённых рабочих мест.
""",
            ["it", "director", "hr"],
        ),
        (
            "Технологическая инструкция: резка рулона",
            "cutting.txt",
            """Технологическая инструкция по резке рулонной бумаги

1. Перед запуском линии проверить натяжение и кромку.
2. Скорость резки задаётся мастером смены по производственному заданию.
3. При обнаружении дефекта кромки — останов линии и акт ОТК.
4. Упаковка партии — по стандарту упаковки для данного формата.
""",
            ["production", "otk", "director"],
        ),
        (
            "Стандарт приёмочного контроля готовой продукции",
            "otk_acceptance.txt",
            """Стандарт приёмочного контроля готовой продукции

1. Выборочный контроль — по плану выборки смены.
2. Несоответствия фиксируются в журнале ОТК с указанием партии.
3. Брак изолируется и маркируется красной биркой.
4. Повторный контроль — после устранения причин.
""",
            ["otk", "production", "director"],
        ),
        (
            "Памятка отдела кадров: отпуска",
            "hr_vacation.txt",
            """Памятка по оформлению отпусков

1. Заявление подаётся не позднее чем за 14 дней до даты (если иное не согласовано).
2. Согласование с непосредственным руководителем обязательно.
3. График отпусков утверждается ежегодно.
""",
            ["hr", "director"],
        ),
    ]

    ud = Path(settings.upload_dir)
    if not ud.is_absolute():
        ud = BACKEND_ROOT / ud
    ud.mkdir(parents=True, exist_ok=True)

    for title, fname, body, role_codes in samples:
        path = kb_dir / fname
        path.write_text(body, encoding="utf-8")
        dest = ud / fname
        dest.write_text(body, encoding="utf-8")
        doc = Document(
            title=title,
            original_filename=fname,
            storage_path=normalize_storage_path(dest),
            mime_type="text/plain",
            uploaded_by_id=admin_id,
        )
        db.add(doc)
        db.flush()
        ids = [roles[c] for c in role_codes]
        attach_roles(db, doc, ids)
        reindex_document(db, doc)

    db.commit()


_log = logging.getLogger(__name__)


def init_extensions(engine) -> None:
    """Включает расширение pgvector (образ БД из docker-compose). Эмбеддинги хранятся в JSON."""
    if engine.dialect.name != "postgresql":
        return
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
    except Exception as exc:
        _log.warning("Не удалось выполнить CREATE EXTENSION vector: %s", exc)


def _migrations_dir() -> Path | None:
    """Расположение SQL-миграций. В Docker — /app/migrations, локально — backend/migrations."""
    candidates = [
        Path("/app/migrations"),
        BACKEND_ROOT / "migrations",
        Path(__file__).resolve().parent.parent / "migrations",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return None


def apply_sql_migrations(engine, filenames: list[str]) -> None:
    """Применяет идемпотентные SQL-миграции (CREATE/ALTER ... IF NOT EXISTS, ON CONFLICT DO NOTHING).

    Нужно потому, что Base.metadata.create_all() не добавляет колонки в уже существующие таблицы:
    после расширения схемы (миграция 002) в БД на Render отсутствовала колонка users.department_id,
    из-за чего падал запрос db.query(User).count() на старте приложения.
    """
    if engine.dialect.name != "postgresql":
        return
    mdir = _migrations_dir()
    if mdir is None:
        _log.warning("Папка с SQL-миграциями не найдена; пропускаю apply_sql_migrations")
        return
    for fname in filenames:
        path = mdir / fname
        if not path.is_file():
            _log.warning("SQL-миграция не найдена: %s", path)
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            # AUTOCOMMIT: BEGIN/COMMIT уже есть внутри SQL-скрипта, своя транзакция SQLAlchemy не нужна.
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.exec_driver_sql(sql)
            _log.info("SQL-миграция применена: %s", fname)
        except Exception as exc:
            _log.error("Ошибка применения SQL-миграции %s: %s", fname, exc)
            raise
