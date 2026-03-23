"""Embedding runtime support."""

from __future__ import annotations

import base64
import threading
from pathlib import Path

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
                model = SentenceTransformer(self._resolve_local_model_path(model_name), local_files_only=True)
                self._models[model_name] = model
            return model

    def _resolve_local_model_path(self, model_name: str) -> str:
        if "/" not in model_name:
            return model_name
        cache_root = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{model_name.replace('/', '--')}"
        ref_path = cache_root / "refs" / "main"
        if ref_path.is_file():
            snapshot = cache_root / "snapshots" / ref_path.read_text().strip()
            if snapshot.is_dir():
                return str(snapshot)
        snapshots_dir = cache_root / "snapshots"
        if snapshots_dir.is_dir():
            snapshots = sorted(path for path in snapshots_dir.iterdir() if path.is_dir())
            if snapshots:
                return str(snapshots[-1])
        return model_name
