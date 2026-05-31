#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Добавляет роль admin ко всем документам базы знаний (идемпотентно)."""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import Document, Role  # noqa: E402
from app.services.ingest import attach_roles  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        admin = db.query(Role).filter(Role.code == "admin").first()
        if not admin:
            print("Ошибка: роль admin не найдена", file=sys.stderr)
            return 1

        docs = db.query(Document).options(joinedload(Document.allowed_roles)).all()
        updated = 0
        for doc in docs:
            current_ids = {r.id for r in doc.allowed_roles}
            if admin.id in current_ids:
                continue
            attach_roles(db, doc, list(current_ids))
            updated += 1
            print(f"Добавлен admin: {doc.title}")

        db.commit()
        print(f"Готово. Обновлено документов: {updated} из {len(docs)}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
