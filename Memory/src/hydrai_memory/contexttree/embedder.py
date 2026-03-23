"""Hydrai Intelligence-backed embedder client for ContexTree."""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import struct

import httpx

from .prompt_config import load_summary_config

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None
    _HAS_NUMPY = False

logger = logging.getLogger(__name__)

_TIMEOUT = 60.0


def _decode_float32_vector(raw: bytes):
    count = len(raw) // 4
    if _HAS_NUMPY:
        return np.frombuffer(raw, dtype=np.float32)
    if count == 0:
        return []
    return list(struct.unpack(f"<{count}f", raw[: count * 4]))


def _vector_norm(vec) -> float:
    if _HAS_NUMPY:
        return float(np.linalg.norm(vec))
    return math.sqrt(sum(float(v) * float(v) for v in vec))


def _vector_dot(vec_a, vec_b) -> float:
    if _HAS_NUMPY:
        return float(np.dot(vec_a, vec_b))
    return sum(float(a) * float(b) for a, b in zip(vec_a, vec_b))


def _internal_auth_headers() -> dict[str, str]:
    if os.environ.get("HYDRAI_SECURITY_MODE", "dev").strip().lower() != "secure":
        return {}
    token_id = os.environ.get("HYDRAI_INTERNAL_TOKEN_ID", "").strip()
    token = os.environ.get("HYDRAI_INTERNAL_TOKEN", "").strip()
    if token_id and token:
        return {"X-Hydrai-Token-Id": token_id, "X-Hydrai-Token": token}
    raw = os.environ.get("HYDRAI_INTERNAL_TOKENS_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid HYDRAI_INTERNAL_TOKENS_JSON") from exc
        if isinstance(parsed, dict):
            for key in sorted(parsed):
                value = str(parsed[key]).strip()
                if value:
                    return {"X-Hydrai-Token-Id": str(key), "X-Hydrai-Token": value}
    raise ValueError("secure mode requires outbound Hydrai internal token material")


class Embedder:
    """Route-local base64 embedding client."""

    def __init__(self, *, intelligence_base_url: str, route_port: int):
        base = str(intelligence_base_url or "").rstrip("/")
        if not base:
            raise ValueError("intelligence_base_url is required")
        if not isinstance(route_port, int) or route_port <= 0:
            raise ValueError("route_port must be a positive int")
        self.intelligence_base_url = base
        self.route_port = route_port

    @property
    def endpoint(self) -> str:
        return f"{self.intelligence_base_url}:{self.route_port}/v1/embeddings"

    def embed(self, text: str) -> str:
        try:
            resp = httpx.post(
                self.endpoint,
                json={"input": str(text or "")},
                headers=_internal_auth_headers(),
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            item = ((data.get("data") or [{}])[0]) if isinstance(data.get("data"), list) else {}
            vector = item.get("embedding", "")
            return vector if isinstance(vector, str) else ""
        except Exception as exc:
            logger.warning("Embedding request failed: %s", exc)
            return ""

    def decode(self, vec_b64: str):
        return _decode_float32_vector(base64.b64decode(vec_b64))

    def similarity(self, vec_a, vec_b) -> float:
        norm_a = _vector_norm(vec_a)
        norm_b = _vector_norm(vec_b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return _vector_dot(vec_a, vec_b) / (norm_a * norm_b)


def build_proxy_embedder(config_path: str) -> Embedder:
    if not config_path:
        raise ValueError("config_path is required for Intelligence-backed embeddings")
    cfg = load_summary_config(config_path)
    return Embedder(
        intelligence_base_url=cfg.intelligence_base_url,
        route_port=cfg.embedder_port,
    )
