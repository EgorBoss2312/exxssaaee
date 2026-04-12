#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генерирует 20 текстовых файлов инструкций и соглашений (демо) и загружает их в БД.

Запуск из каталога backend:
    python scripts/load_labor_documents.py

Повторный запуск не дублирует записи: пропускает документы с тем же original_filename.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

# корень backend (родитель каталога scripts)
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.labor_kb_build import build_documents  # noqa: E402
from app.models import Document, Role, User  # noqa: E402
from app.services.ingest import attach_roles, reindex_document  # noqa: E402


def _upload_dir_abs(settings) -> Path:
    p = Path(settings.upload_dir)
    if p.is_absolute():
        return p
    return _BACKEND_ROOT / p


def main() -> int:
    kb_dir = _BACKEND_ROOT / "seed_kb" / "labor_docs"
    kb_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    upload_dir = _upload_dir_abs(settings)
    upload_dir.mkdir(parents=True, exist_ok=True)

    specs = build_documents()
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == "admin@edda.local").first()
        if not admin:
            print(
                "Ошибка: в базе нет пользователя admin@edda.local. "
                "Запустите приложение один раз, чтобы выполнить начальное заполнение БД.",
                file=sys.stderr,
            )
            return 1

        roles_map = {r.code: r.id for r in db.query(Role).all()}
        for _, _, role_codes, _ in specs:
            for c in role_codes:
                if c not in roles_map:
                    print(f"Ошибка: в БД нет роли {c!r}", file=sys.stderr)
                    return 1

        inserted = 0
        skipped = 0

        for title, fname, role_codes, body in specs:
            seed_path = kb_dir / fname
            seed_path.write_text(body, encoding="utf-8")

            existing = db.query(Document).filter(Document.original_filename == fname).first()
            if existing:
                skipped += 1
                continue

            stored_name = f"labor_seed_{uuid.uuid4().hex[:10]}_{fname}"
            dest = upload_dir / stored_name
            dest.write_text(body, encoding="utf-8")

            doc = Document(
                title=title,
                original_filename=fname,
                storage_path=str(dest),
                mime_type="text/plain",
                uploaded_by_id=admin.id,
            )
            db.add(doc)
            db.flush()

            rids = [roles_map[c] for c in role_codes]
            attach_roles(db, doc, rids)
            reindex_document(db, doc)
            inserted += 1

        db.commit()
        print(f"Файлы записаны в: {kb_dir}")
        print(f"Добавлено в БД документов: {inserted}")
        print(f"Пропущено (уже существуют по original_filename): {skipped}")
        return 0
    except Exception as e:
        db.rollback()
        print(f"Ошибка: {e}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
