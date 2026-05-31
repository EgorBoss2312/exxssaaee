from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select

from app.config import BACKEND_ROOT, get_settings
from app.database import get_db
from app.deps import get_current_user, require_kb_manager
from app.models import Document, DocumentTag, Role, User, document_roles
from app.schemas import DocumentOut, DocumentTagOut
from app.services.audit import write_audit
from app.services.ingest import attach_roles, reindex_document
from app.storage_paths import normalize_storage_path, resolve_storage_path

router = APIRouter(prefix="/documents", tags=["documents"])


def _doc_to_out(doc: Document) -> DocumentOut:
    names = [r.code for r in doc.allowed_roles]
    uploader = doc.uploaded_by_user.full_name if doc.uploaded_by_user else None
    tag_out = [
        DocumentTagOut(id=t.id, code=t.code, name=t.name, color=t.color)
        for t in (doc.tags or [])
    ]
    return DocumentOut(
        id=doc.id,
        title=doc.title,
        original_filename=doc.original_filename,
        mime_type=doc.mime_type,
        created_at=doc.created_at,
        uploaded_by_name=uploader,
        allowed_role_codes=names,
        tags=tag_out,
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
    docs = (
        _list_query(db, user)
        .options(joinedload(Document.allowed_roles), joinedload(Document.tags))
        .all()
    )
    return [_doc_to_out(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(
    doc_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    doc = (
        db.query(Document)
        .options(joinedload(Document.allowed_roles), joinedload(Document.tags))
        .filter(Document.id == doc_id)
        .first()
    )
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
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_manager)],
    title: str = Form(...),
    allowed_role_ids: str = Form(...),
    file: UploadFile = File(...),
    tag_ids: str = Form("[]"),
):
    try:
        ids: list[int] = json.loads(allowed_role_ids)
        if not isinstance(ids, list) or not ids:
            raise ValueError("role ids")
    except Exception:
        raise HTTPException(status_code=400, detail="allowed_role_ids должен быть JSON-массивом целых чисел")

    try:
        raw_tag_ids = json.loads(tag_ids)
        if not isinstance(raw_tag_ids, list):
            raise ValueError("tag ids not a list")
        tag_id_list: list[int] = []
        for x in raw_tag_ids:
            if type(x) is not int:
                raise ValueError("tag id must be int")
            tag_id_list.append(x)
    except Exception:
        raise HTTPException(status_code=400, detail="tag_ids должен быть JSON-массивом целых чисел (id тегов)")

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

    if tag_id_list:
        tags = db.query(DocumentTag).filter(DocumentTag.id.in_(tag_id_list)).all()
        found = {t.id for t in tags}
        missing = set(tag_id_list) - found
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Неизвестные id тегов: {sorted(missing)}",
            )
        doc.tags = tags

    db.refresh(doc)

    reindex_document(db, doc)

    write_audit(
        db,
        actor_id=user.id,
        action="document_upload",
        object_type="document",
        object_id=doc.id,
        details={
            "title": doc.title,
            "filename": doc.original_filename,
            "role_ids": ids,
            "tag_ids": tag_id_list,
        },
        request=request,
    )

    db.commit()
    doc = (
        db.query(Document)
        .options(joinedload(Document.allowed_roles), joinedload(Document.tags))
        .filter(Document.id == doc.id)
        .first()
    )
    assert doc is not None
    return _doc_to_out(doc)


@router.post("/reindex")
def reindex_documents(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_manager)],
):
    """
    Пересчитать текст и эмбеддинги для всех документов (актуализация базы знаний).
    Доступно администратору и ИТ.
    """
    docs = db.query(Document).order_by(Document.id.asc()).all()
    reindexed = 0
    missing = 0
    normalized = 0
    for doc in docs:
        path = resolve_storage_path(doc.storage_path)
        if not path.is_file():
            missing += 1
            reindex_document(db, doc)
            reindexed += 1
            continue
        new_sp = normalize_storage_path(path)
        if doc.storage_path != new_sp:
            doc.storage_path = new_sp
            normalized += 1
        reindex_document(db, doc)
        reindexed += 1

    write_audit(
        db,
        actor_id=user.id,
        action="documents_reindex",
        object_type="document",
        object_id=None,
        details={
            "reindexed": reindexed,
            "missing_files": missing,
            "paths_normalized": normalized,
            "total": len(docs),
        },
        request=request,
    )

    db.commit()
    return {
        "reindexed": reindexed,
        "missing_files": missing,
        "paths_normalized": normalized,
        "total": len(docs),
    }


@router.put("/{doc_id}/file", response_model=DocumentOut)
async def replace_document_file(
    doc_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_manager)],
    file: UploadFile = File(...),
):
    """Заменить файл документа новой версией с компьютера пользователя."""
    doc = (
        db.query(Document)
        .options(joinedload(Document.allowed_roles), joinedload(Document.tags))
        .filter(Document.id == doc_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")

    old_path = resolve_storage_path(doc.storage_path)
    old_filename = doc.original_filename

    settings = get_settings()
    os.makedirs(settings.upload_dir, exist_ok=True)
    ext = Path(file.filename or "file").suffix
    stored = f"{uuid.uuid4().hex}{ext}"
    ud = Path(settings.upload_dir)
    dest = (BACKEND_ROOT / ud / stored) if not ud.is_absolute() else (ud / stored)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    doc.original_filename = file.filename or stored
    doc.mime_type = file.content_type
    doc.storage_path = normalize_storage_path(dest)

    reindex_document(db, doc)

    write_audit(
        db,
        actor_id=user.id,
        action="document_replace",
        object_type="document",
        object_id=doc.id,
        details={
            "title": doc.title,
            "old_filename": old_filename,
            "new_filename": doc.original_filename,
        },
        request=request,
    )

    db.commit()

    try:
        if old_path.is_file() and old_path.resolve() != dest.resolve():
            old_path.unlink()
    except OSError:
        pass

    db.refresh(doc)
    return _doc_to_out(doc)


@router.post("/{doc_id}/reindex")
def reindex_one_document(
    doc_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_manager)],
):
    """Пересчитать текст и эмбеддинги одного документа."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")

    path = resolve_storage_path(doc.storage_path)
    file_missing = not path.is_file()
    path_normalized = False
    if not file_missing:
        new_sp = normalize_storage_path(path)
        if doc.storage_path != new_sp:
            doc.storage_path = new_sp
            path_normalized = True

    reindex_document(db, doc)

    write_audit(
        db,
        actor_id=user.id,
        action="document_reindex",
        object_type="document",
        object_id=doc.id,
        details={
            "title": doc.title,
            "filename": doc.original_filename,
            "file_missing": file_missing,
            "path_normalized": path_normalized,
        },
        request=request,
    )

    db.commit()
    return {
        "ok": True,
        "document_id": doc.id,
        "file_missing": file_missing,
        "path_normalized": path_normalized,
    }


@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_manager)],
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Не найдено")
    path = resolve_storage_path(doc.storage_path)

    write_audit(
        db,
        actor_id=user.id,
        action="document_delete",
        object_type="document",
        object_id=doc.id,
        details={"title": doc.title, "filename": doc.original_filename},
        request=request,
    )

    db.delete(doc)
    db.commit()
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass
    return {"ok": True}
