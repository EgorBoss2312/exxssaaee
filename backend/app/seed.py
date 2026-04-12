import os
from pathlib import Path

from sqlalchemy.orm import Session

from app.auth_core import hash_password
from app.config import get_settings
from app.models import Document, Role, User
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

    demos_data = [
        ("director@edda.local", "Director123!", "Иванов И.И.", "director"),
        ("hr@edda.local", "Hr123456!", "Петрова А.С.", "hr"),
        ("prod@edda.local", "Prod123456!", "Сидоров П.П.", "production"),
        ("otk@edda.local", "Otk123456!", "Козлова Е.В.", "otk"),
        ("it@edda.local", "It123456!", "Смирнов Д.Д.", "it"),
    ]
    for email, pw, name, code in demos_data:
        db.add(
            User(
                email=email,
                hashed_password=hash_password(pw),
                full_name=name,
                role_id=roles[code],
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

    os.makedirs(settings.upload_dir, exist_ok=True)

    for title, fname, body, role_codes in samples:
        path = kb_dir / fname
        path.write_text(body, encoding="utf-8")
        dest = Path(settings.upload_dir) / fname
        dest.write_text(body, encoding="utf-8")
        doc = Document(
            title=title,
            original_filename=fname,
            storage_path=str(dest),
            mime_type="text/plain",
            uploaded_by_id=admin_id,
        )
        db.add(doc)
        db.flush()
        ids = [roles[c] for c in role_codes]
        attach_roles(db, doc, ids)
        reindex_document(db, doc)

    db.commit()


def init_extensions(engine) -> None:
    """Расширения СУБД (раньше — pgvector). Сейчас эмбеддинги в JSON, вызов оставлен для совместимости."""
    _ = engine
