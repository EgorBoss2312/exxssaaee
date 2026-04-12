from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Document, Role
from app.services.chunking import chunk_text
from app.services.embeddings import embed_texts
from app.services.text_extract import extract_text_from_file


def reindex_document(db: Session, doc: Document) -> None:
    settings = get_settings()
    path = Path(doc.storage_path)
    if not path.is_file():
        doc.text_content = ""
    else:
        doc.text_content = extract_text_from_file(path, doc.mime_type)

    db.query(Chunk).filter(Chunk.document_id == doc.id).delete(synchronize_session=False)
    db.flush()

    parts = chunk_text(doc.text_content or "")
    if not parts:
        placeholder = "Пустой документ или не удалось извлечь текст."
        parts = [placeholder]

    emb = embed_texts(parts, settings.embedding_model)
    for i, (text, row) in enumerate(zip(parts, emb)):
        vec = np.asarray(row, dtype=float).tolist()
        ch = Chunk(
            document_id=doc.id,
            chunk_index=i,
            content=text,
            embedding=vec,
        )
        db.add(ch)
    db.flush()


def attach_roles(db: Session, doc: Document, role_ids: list[int]) -> None:
    roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
    doc.allowed_roles = roles
    db.flush()
