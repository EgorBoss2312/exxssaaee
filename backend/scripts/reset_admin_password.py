#!/usr/bin/env python3
"""
Сброс пароля пользователя admin@edda.local.

Используйте, если в БД уже есть учётные записи (seed при первом запуске не повторяется),
а демо-пароль не подходит — например, при первом старте Docker был задан SEED_ADMIN_PASSWORD.

Запуск из каталога backend (с активированным .venv):

  python scripts/reset_admin_password.py
  python scripts/reset_admin_password.py 'МойНовыйПароль123!'
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth_core import hash_password
from app.database import SessionLocal
from app.models import User


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    new_pw = args[0] if args else "Admin123!"
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "admin@edda.local").first()
        if not u:
            print("Пользователь admin@edda.local не найден в базе.", file=sys.stderr)
            return 1
        u.hashed_password = hash_password(new_pw)
        db.commit()
        print(f"Пароль для admin@edda.local обновлён (длина нового пароля: {len(new_pw)} символов).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
