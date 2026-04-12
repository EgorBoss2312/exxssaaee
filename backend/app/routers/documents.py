from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select

from app.config import BACKEND_ROOT, get_settings
from app.database import get_db
from app.deps import get_current_user, require_kb_manager
from app.models import Document, Role, User, document_roles
from app.schemas import DocumentOut
from app.services.ingest import attach_roles, reindex_document
from app.storage_paths import normalize_storage_path, resolve_storage_path

router = APIRouter(prefix="/documents", tags=["documents"])


def _doc_to_out(doc: Document) -> DocumentOut:
    names = [r.code for r in doc.allowed_roles]
    uploader = doc.uploaded_by_user.full_name if doc.uploaded_by_user else None
    return DocumentOut(
        id=doc.id,
        title=doc.title,
        original_filename=doc.original_filename,
        mime_type=doc.mime_type,
        created_at=doc.created_at,
        uploaded_by_name=uploader,
        allowed_role_codes=names,
    )


def _list_query(db: Session, user: User):
    q = db.query(Document)
    if user.role.code != "admin":
        subq = select(document_roles.c.document_id).where(
            document_roles.c.role_id == user.role_id
        )
        q = q.filter(Document.id.in_(subq))
    return q.order_by(Document.created_at.desc())


@router.get("", response_model=list[DocumentOut])
def list_documents(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    docs = _list_query(db, user).options(joinedload(Document.allowed_roles)).all()
    return [_doc_to_out(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(
    doc_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if user.role.code != "admin":
        allowed = {r.id for r in doc.allowed_roles}
        if user.role_id not in allowed:
            raise HTTPException(status_code=403, detail="Нет доступа к документу")
    return _doc_to_out(doc)


@router.get("/{doc_id}/preview")
def preview_document(
    doc_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if user.role.code != "admin":
        allowed = {r.id for r in doc.allowed_roles}
        if user.role_id not in allowed:
            raise HTTPException(status_code=403, detail="Нет доступа")
    return {"text": (doc.text_content or "")[:50000]}


@router.get("/{doc_id}/file")
def download_file(
    doc_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if user.role.code != "admin":
        allowed = {r.id for r in doc.allowed_roles}
        if user.role_id not in allowed:
            raise HTTPException(status_code=403, detail="Нет доступа")
    path = resolve_storage_path(doc.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл отсутствует на сервере")
    return FileResponse(path, filename=doc.original_filename, media_type=doc.mime_type or "application/octet-stream")


@router.post("", response_model=DocumentOut)
async def upload_document(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_manager)],
    title: str = Form(...),
    allowed_role_ids: str = Form(...),
    file: UploadFile = File(...),
):
    try:
        ids: list[int] = json.loads(allowed_role_ids)
        if not isinstance(ids, list) or not ids:
            raise ValueError("role ids")
    except Exception:
        raise HTTPException(status_code=400, detail="allowed_role_ids должен быть JSON-массивом целых чисел")

    settings = get_settings()
    os.makedirs(settings.upload_dir, exist_ok=True)
    ext = Path(file.filename or "file").suffix
    stored = f"{uuid.uuid4().hex}{ext}"
    ud = Path(settings.upload_dir)
    dest = (BACKEND_ROOT / ud / stored) if not ud.is_absolute() else (ud / stored)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    doc = Document(
        title=title.strip(),
        original_filename=file.filename or stored,
        storage_path=normalize_storage_path(dest),
        mime_type=file.content_type,
        uploaded_by_id=user.id,
    )
    db.add(doc)
    db.flush()

    attach_roles(db, doc, ids)
    db.refresh(doc)

    reindex_document(db, doc)
    db.commit()
    db.refresh(doc)
    return _doc_to_out(doc)


@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_manager)],
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Не найдено")
    path = resolve_storage_path(doc.storage_path)
    db.delete(doc)
    db.commit()
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass
    return {"ok": True}
