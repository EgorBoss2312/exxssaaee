from __future__ import annotations

import hashlib
import os
import threading

import numpy as np

# Размерность как у paraphrase-multilingual-MiniLM-L12-v2 (совместимость с косинусом в RAG)
_EMB_DIM = 384

_model = None
_lock = threading.Lock()
_model_name: str | None = None


def _use_hash_embeddings() -> bool:
    """Без PyTorch/sentence-transformers — укладывается в ~512MB (Render Free и аналоги)."""
    v = os.environ.get("EDDA_USE_HASH_EMBEDDINGS", "").strip().lower()
    return v in ("1", "true", "yes")


def _hash_embed_texts(texts: list[str]) -> np.ndarray:
    """Детерминированные псевдо-векторы (качество поиска ниже, чем у ML-модели)."""
    rows: list[np.ndarray] = []
    for t in texts:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        buf = bytearray(h)
        while len(buf) < _EMB_DIM:
            buf.extend(hashlib.sha256(bytes(buf)).digest())
        x = np.frombuffer(bytes(buf[:_EMB_DIM]), dtype=np.uint8).astype(np.float32)
        x = (x / 255.0) * 2.0 - 1.0
        n = float(np.linalg.norm(x)) or 1.0
        rows.append(x / n)
    return np.vstack(rows) if rows else np.zeros((0, _EMB_DIM), dtype=np.float32)


def get_model(name: str):
    global _model, _model_name
    if _use_hash_embeddings():
        raise RuntimeError("get_model() недоступен при EDDA_USE_HASH_EMBEDDINGS=1")
    with _lock:
        if _model is None or _model_name != name:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(name)
            _model_name = name
        return _model


def embed_texts(texts: list[str], model_name: str) -> np.ndarray:
    if not texts:
        return np.zeros((0, 0))
    if _use_hash_embeddings():
        return _hash_embed_texts(texts)
    model = get_model(model_name)
    emb = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return np.asarray(emb, dtype=np.float32)


def embed_query(text: str, model_name: str) -> list[float]:
    if _use_hash_embeddings():
        v = _hash_embed_texts([text])[0]
        return np.asarray(v, dtype=np.float32).tolist()
    model = get_model(model_name)
    v = model.encode([text], convert_to_numpy=True, show_progress_bar=False)[0]
    return np.asarray(v, dtype=np.float32).tolist()
