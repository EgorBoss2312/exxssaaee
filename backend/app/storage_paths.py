"""Переносимые пути к файлам в БД: без абсолютных /Users/... с локальной машины."""

from __future__ import annotations

from pathlib import Path

from app.config import BACKEND_ROOT, get_settings


def upload_dir_resolved() -> Path:
    s = get_settings()
    ud = Path(s.upload_dir)
    if ud.is_absolute():
        return ud.resolve()
    return (BACKEND_ROOT / ud).resolve()


def normalize_storage_path(path: Path) -> str:
    """Сохраняем в БД путь относительно BACKEND_ROOT (например data/uploads/name.txt)."""
    path = path.resolve()
    br = BACKEND_ROOT.resolve()
    try:
        return path.relative_to(br).as_posix()
    except ValueError:
        return path.name


def resolve_storage_path(storage_path: str) -> Path:
    """
    Находит файл на диске: относительный путь от корня backend, либо по имени в upload_dir,
    если в БД остался чужой абсолютный путь (Mac/Windows).
    """
    raw = (storage_path or "").strip()
    if not raw:
        return Path("")
    p = Path(raw)
    # Сначала путь как в БД относительно корня приложения (data/uploads/...)
    if not p.is_absolute():
        rel = (BACKEND_ROOT / raw).resolve()
        if rel.is_file():
            return rel
    if p.is_file():
        return p.resolve()

    ud = upload_dir_resolved()
    by_name = ud / p.name
    if by_name.is_file():
        return by_name.resolve()

    rel2 = (BACKEND_ROOT / raw.lstrip("/")).resolve()
    if rel2.is_file():
        return rel2

    return p
