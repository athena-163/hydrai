"""Internal auth gate for Toolbox."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


class AuthError(Exception):
    """Raised when internal auth material is invalid or missing."""


@dataclass(frozen=True)
class InternalAuthGate:
    mode: str
    tokens: dict[str, str]

    @classmethod
    def from_env(cls) -> "InternalAuthGate":
        mode = os.environ.get("HYDRAI_SECURITY_MODE", "dev").strip().lower() or "dev"
        if mode not in {"dev", "secure"}:
            raise AuthError(f"unsupported HYDRAI_SECURITY_MODE: {mode}")

        raw = os.environ.get("HYDRAI_INTERNAL_TOKENS_JSON", "").strip()
        tokens: dict[str, str] = {}
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise AuthError("invalid HYDRAI_INTERNAL_TOKENS_JSON") from exc
            if not isinstance(parsed, dict):
                raise AuthError("HYDRAI_INTERNAL_TOKENS_JSON must be an object")
            tokens = {str(k): str(v) for k, v in parsed.items() if str(v)}
        else:
            token_id = os.environ.get("HYDRAI_INTERNAL_TOKEN_ID", "").strip()
            token = os.environ.get("HYDRAI_INTERNAL_TOKEN", "").strip()
            if token_id and token:
                tokens[token_id] = token

        if mode == "secure" and not tokens:
            raise AuthError("secure mode requires internal auth tokens")
        return cls(mode=mode, tokens=tokens)

    def check(self, token_id: str | None, token: str | None) -> bool:
        if self.mode == "dev":
            return True
        if not token_id or not token:
            return False
        return self.tokens.get(token_id) == token
