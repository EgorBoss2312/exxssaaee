from __future__ import annotations

import threading
from typing import Any

import numpy as np

_model = None
_lock = threading.Lock()
_model_name: str | None = None


def get_model(name: str):
    global _model, _model_name
    with _lock:
        if _model is None or _model_name != name:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(name)
            _model_name = name
        return _model


def embed_texts(texts: list[str], model_name: str) -> np.ndarray:
    if not texts:
        return np.zeros((0, 0))
    model = get_model(model_name)
    emb = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return np.asarray(emb, dtype=np.float32)


def embed_query(text: str, model_name: str) -> list[float]:
    model = get_model(model_name)
    v = model.encode([text], convert_to_numpy=True, show_progress_bar=False)[0]
    return np.asarray(v, dtype=np.float32).tolist()
