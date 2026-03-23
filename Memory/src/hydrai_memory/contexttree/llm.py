"""Hydrai Intelligence clients for text, image, and video summarization."""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import json

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 60.0


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


class LLMClient:
    """Client for route-local OpenAI-style text summarization."""

    def __init__(self, base_url: str, model: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def summarize_text(self, content: str) -> str:
        return self.summarize(
            content,
            (
                "Summarize the following content. Aim for 10:1 compression with highly "
                "informative and compact words, keep at least 1-2 sentences for short "
                "content, while no more than 500 tokens for very long one."
            ),
            max_tokens=512,
        )

    def summarize_folder(self, folder_view: str) -> str:
        return self.summarize(
            folder_view,
            "Summarize this folder's contents. Write 1-2 sentences describing the folder's overall purpose.",
            max_tokens=200,
        )

    def summarize(self, content: str, system_prompt: str, max_tokens: int = 512) -> str:
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "max_tokens": max_tokens,
        }
        if self.model:
            payload["model"] = self.model
        try:
            resp = httpx.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=_internal_auth_headers(),
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data["choices"][0]["message"]["content"] or "").strip()
        except Exception as exc:
            logger.warning("LLM summarize request failed: %s", exc)
            return ""


class VLClient:
    """Client for route-local multimodal summarization."""

    def __init__(self, base_url: str, model: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def summarize_image(self, image_path: str, mime_type: str, prompt: str = "Describe this image concisely.") -> str:
        return self.summarize_media(image_path, prompt, mime_type=mime_type)

    def summarize_media(self, media_path: str, prompt: str, mime_type: str | None = None) -> str:
        mime = mime_type or mimetypes.guess_type(media_path)[0] or "application/octet-stream"
        try:
            with open(media_path, "rb") as f:
                b64data = base64.b64encode(f.read()).decode("ascii")
        except OSError as exc:
            logger.warning("Cannot read media file %s: %s", media_path, exc)
            return ""

        if mime.startswith("video/"):
            item_type = "video_url"
            item_value = {"video_url": {"url": f"data:{mime};base64,{b64data}"}}
        else:
            item_type = "image_url"
            item_value = {"image_url": {"url": f"data:{mime};base64,{b64data}"}}
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": item_type,
                            **item_value,
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
            "max_tokens": 256,
        }
        if self.model:
            payload["model"] = self.model
        try:
            resp = httpx.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=_internal_auth_headers(),
                timeout=300.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data["choices"][0]["message"]["content"] or "").strip()
        except Exception as exc:
            logger.warning("VL summarize request failed: %s", exc)
            return ""


class ProxyLLMClient:
    """Config-driven route-local summarization client."""

    def __init__(self, intelligence_base_url: str):
        self.intelligence_base_url = intelligence_base_url.rstrip("/")

    def summarize(self, content: str, system_prompt: str, route_port: int, max_tokens: int = 512) -> str:
        client = LLMClient(f"{self.intelligence_base_url}:{route_port}")
        return client.summarize(content, system_prompt, max_tokens=max_tokens)


class ProxyVLClient:
    """Config-driven route-local multimodal client."""

    def __init__(self, intelligence_base_url: str):
        self.intelligence_base_url = intelligence_base_url.rstrip("/")

    def summarize_media(self, media_path: str, route_port: int, prompt: str) -> str:
        client = VLClient(f"{self.intelligence_base_url}:{route_port}")
        return client.summarize_media(media_path, prompt)
