"""Embedding runtime support."""

from __future__ import annotations

import base64
import threading

import numpy
from sentence_transformers import SentenceTransformer


class EmbeddingBackend:
    def __init__(self):
        self._models: dict[str, SentenceTransformer] = {}
        self._lock = threading.Lock()

    def embed(self, model_name: str, text: str) -> tuple[str, int]:
        model = self._get_model(model_name)
        vec = model.encode(str(text or ""), normalize_embeddings=True)
        arr = numpy.asarray(vec, dtype=numpy.float32)
        return base64.b64encode(arr.tobytes()).decode("ascii"), int(arr.shape[0])

    def _get_model(self, model_name: str) -> SentenceTransformer:
        with self._lock:
            model = self._models.get(model_name)
            if model is None:
                model = SentenceTransformer(model_name)
                self._models[model_name] = model
            return model

