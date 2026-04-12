from __future__ import annotations

import io
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


def extract_text_from_file(path: Path, mime: str | None) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf" or (mime and "pdf" in mime):
        return _pdf_text(path)
    if suffix in (".docx", ".doc") or (mime and "word" in mime):
        return _docx_text(path)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    # fallback: try as text
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text() or ""
        parts.append(t)
    return "\n\n".join(parts).strip()


def _docx_text(path: Path) -> str:
    doc = DocxDocument(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text).strip()


def extract_text_from_bytes(data: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n\n".join(parts).strip()
    if suffix == ".docx":
        doc = DocxDocument(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text).strip()
    return data.decode("utf-8", errors="replace")
