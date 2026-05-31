#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Синхронизирует роли доступа для общекорпоративных HR-документов в уже загруженной БД."""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import SessionLocal  # noqa: E402
from app.enterprise_kb_build import ALL_STAFF_ROLES  # noqa: E402
from app.models import Document, Role  # noqa: E402
from app.services.ingest import attach_roles  # noqa: E402

_HR_FILENAMES = {
    "polozhenie_hr_priem_adaptaciya.txt",
    "reglament_otpusk_bolnichnye.txt",
    "hr_vacation.txt",
}


def main() -> int:
    db = SessionLocal()
    try:
        roles_map = {r.code: r.id for r in db.query(Role).all()}
        missing = [c for c in ALL_STAFF_ROLES if c not in roles_map]
        if missing:
            print(f"Ошибка: нет ролей {missing}", file=sys.stderr)
            return 1

        updated = 0
        for fname in _HR_FILENAMES:
            doc = db.query(Document).filter(Document.original_filename == fname).first()
            if not doc:
                print(f"Пропуск (нет в БД): {fname}")
                continue
            attach_roles(db, doc, [roles_map[c] for c in ALL_STAFF_ROLES])
            updated += 1
            print(f"Обновлены роли: {doc.title}")

        db.commit()
        print(f"Готово. Обновлено документов: {updated}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
