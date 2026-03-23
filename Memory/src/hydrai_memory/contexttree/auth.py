"""Outbound Hydrai internal auth helpers for ContexTree -> Intelligence."""

from __future__ import annotations

import json
import os


def build_internal_auth_headers(route_port: int | None = None) -> dict[str, str]:
    if os.environ.get("HYDRAI_SECURITY_MODE", "dev").strip().lower() != "secure":
        return {}

    token_id = os.environ.get("HYDRAI_INTERNAL_TOKEN_ID", "").strip()
    token = os.environ.get("HYDRAI_INTERNAL_TOKEN", "").strip()
    if token_id and token:
        return {"X-Hydrai-Token-Id": token_id, "X-Hydrai-Token": token}

    if route_port is not None:
        raw = os.environ.get("HYDRAI_INTELLIGENCE_ROUTE_TOKENS_JSON", "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid HYDRAI_INTELLIGENCE_ROUTE_TOKENS_JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError("HYDRAI_INTELLIGENCE_ROUTE_TOKENS_JSON must be an object")
            entry = parsed.get(str(route_port))
            if isinstance(entry, dict):
                route_token_id = str(entry.get("token_id", "")).strip()
                route_token = str(entry.get("token", "")).strip()
                if route_token_id and route_token:
                    return {
                        "X-Hydrai-Token-Id": route_token_id,
                        "X-Hydrai-Token": route_token,
                    }
            raise ValueError(f"secure mode requires token material for Intelligence route port {route_port}")

    raise ValueError(
        "secure mode requires HYDRAI_INTERNAL_TOKEN_ID/HYDRAI_INTERNAL_TOKEN "
        "or HYDRAI_INTELLIGENCE_ROUTE_TOKENS_JSON"
    )
