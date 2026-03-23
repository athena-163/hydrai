"""Route adapters."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import RouteConfig
from .embedding import EmbeddingBackend


class IntelligenceError(RuntimeError):
    """Base adapter error."""


class BadRequestError(IntelligenceError):
    """Raised for caller request errors."""


class UnsupportedFeatureError(IntelligenceError):
    """Raised when a feature is unsupported."""


class UpstreamError(IntelligenceError):
    """Raised when upstream handling fails."""

    def __init__(self, status_code: int, payload: Any):
        super().__init__(f"upstream error {status_code}")
        self.status_code = status_code
        self.payload = payload


def _request_json(client: httpx.Client, method: str, url: str, *, headers: dict[str, str] | None = None, json_body: dict[str, Any] | None = None) -> tuple[int, Any]:
    try:
        response = client.request(method, url, headers=headers, json=json_body)
    except httpx.HTTPError as exc:
        raise UpstreamError(502, {"error": f"upstream request failed: {exc}"}) from exc
    data = _json_or_text(response)
    if response.status_code >= 400:
        raise UpstreamError(response.status_code, data)
    return response.status_code, data


def build_adapter(route: RouteConfig, embedding_backend: EmbeddingBackend) -> "BaseAdapter":
    if route.adapter == "remote":
        return RemoteChatAdapter(route)
    if route.adapter == "llama":
        return LlamaChatAdapter(route)
    if route.adapter == "embedding":
        return EmbeddingAdapter(route, embedding_backend)
    raise IntelligenceError(f"unsupported adapter: {route.adapter}")


@dataclass
class BaseAdapter:
    route: RouteConfig

    def startup(self) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        return {
            "name": self.route.name,
            "type": self.route.type,
            "adapter": self.route.adapter,
            "model": self.route.model,
            "search": self.route.search,
            "think": list(self.route.think),
            "modalities": self.route.modalities,
            "context_k": self.route.context_k,
        }


class RemoteChatAdapter(BaseAdapter):
    def __init__(self, route: RouteConfig):
        super().__init__(route)
        self._client: httpx.Client | None = None

    def startup(self) -> None:
        self._client = httpx.Client(timeout=self.route.limits.timeout_sec)

    def shutdown(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def chat(self, body: dict[str, Any]) -> tuple[int, Any]:
        requested_think = str(body.get("think", "off"))
        if requested_think not in {"off", "low", "mid", "high"}:
            raise BadRequestError("think must be one of off/low/mid/high")
        if self.route.think and requested_think not in self.route.think:
            raise UnsupportedFeatureError(f"think='{requested_think}' unsupported on route {self.route.name}")
        search = bool(body.get("search", False))
        if search and not self.route.search:
            raise UnsupportedFeatureError(f"search unsupported on route {self.route.name}")
        _validate_modalities(self.route, body)

        if _is_xai_target(self.route.target) and search:
            upstream_url, payload = _build_xai_responses_request(self.route, body)
            _status, data = _request_json(
                self._client,
                "POST",
                upstream_url,
                headers=_build_auth_headers(self.route),
                json_body=payload,
            )
            return 200, _translate_xai_responses_to_chat(data, self.route.model)

        payload = dict(body)
        payload["model"] = self.route.model
        payload.pop("search", None)
        payload.pop("think", None)
        payload.update(self.route.extra_params)
        if requested_think != "off":
            payload["reasoning_effort"] = requested_think

        return _request_json(
            self._client,
            "POST",
            self.route.target.rstrip("/") + "/v1/chat/completions",
            headers=_build_auth_headers(self.route),
            json_body=payload,
        )


class LlamaChatAdapter(BaseAdapter):
    def __init__(self, route: RouteConfig):
        super().__init__(route)
        self._client: httpx.Client | None = None
        self._proc: subprocess.Popen[str] | None = None
        self._target = f"http://127.0.0.1:{_llama_runtime_port(self.route.listen)}"

    def startup(self) -> None:
        self._client = httpx.Client(timeout=self.route.limits.timeout_sec)
        runtime_port = _llama_runtime_port(self.route.listen)
        self._target = f"http://127.0.0.1:{runtime_port}"
        llama_server_bin = _resolve_llama_server_bin()
        cmd = [
            llama_server_bin,
            "-m",
            self.route.artifact,
            "--host",
            "127.0.0.1",
            "--port",
            str(runtime_port),
            "-c",
            str(max(self.route.context_k, 1) * 1024),
        ]
        if self.route.mmproj:
            cmd.extend(["--mmproj", self.route.mmproj])
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        _wait_for_http(self._target + "/health", timeout_sec=30)

    def shutdown(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def health(self) -> dict[str, Any]:
        data = super().health()
        data["runtime_target"] = self._target
        data["ready"] = _check_http(self._target + "/health")
        return data

    def chat(self, body: dict[str, Any]) -> tuple[int, Any]:
        requested_think = str(body.get("think", "off"))
        if requested_think not in {"off", "low", "mid", "high"}:
            raise BadRequestError("think must be one of off/low/mid/high")
        if self.route.think and requested_think not in self.route.think:
            raise UnsupportedFeatureError(f"think='{requested_think}' unsupported on route {self.route.name}")
        if body.get("search"):
            raise UnsupportedFeatureError(f"search unsupported on route {self.route.name}")
        _validate_modalities(self.route, body)

        payload = dict(body)
        payload["model"] = self.route.model
        payload.pop("search", None)
        payload.pop("think", None)
        if requested_think != "off":
            payload.setdefault("extra_body", {})
            payload["extra_body"]["reasoning_effort"] = requested_think
        return _request_json(
            self._client,
            "POST",
            self._target + "/v1/chat/completions",
            json_body=payload,
        )


class EmbeddingAdapter(BaseAdapter):
    def __init__(self, route: RouteConfig, embedding_backend: EmbeddingBackend):
        super().__init__(route)
        self._backend = embedding_backend

    def embeddings(self, body: dict[str, Any]) -> tuple[int, Any]:
        if "input" not in body:
            raise BadRequestError("embedding request requires 'input'")
        input_value = body["input"]
        if isinstance(input_value, list):
            raise UnsupportedFeatureError("batched embeddings are not supported in v1")
        if not isinstance(input_value, str):
            raise BadRequestError("embedding input must be a string")
        vector, dimension = self._backend.embed(self.route.model, input_value)
        return 200, {
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "index": 0,
                    "embedding": vector,
                    "encoding": "base64",
                    "dimension": dimension,
                }
            ],
            "model": self.route.model,
        }


def _build_auth_headers(route: RouteConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "hydrai-intelligence/0.1"}
    if route.key_env:
        key = os.environ.get(route.key_env, "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
    return headers


def _is_xai_target(target: str) -> bool:
    return "x.ai" in target


def _build_xai_responses_request(route: RouteConfig, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    payload = dict(body)
    messages = payload.pop("messages", None)
    if not isinstance(messages, list):
        raise BadRequestError("messages must be an array")
    payload["model"] = route.model
    payload["input"] = [_translate_message_for_xai(msg) for msg in messages]
    payload.pop("search", None)
    think = payload.pop("think", "off")
    if think != "off":
        payload["reasoning"] = {"effort": think}
    payload["tools"] = [{"type": "web_search"}]
    payload.update(route.extra_params)
    return route.target.rstrip("/") + "/v1/responses", payload


def _translate_message_for_xai(message: dict[str, Any]) -> dict[str, Any]:
    role = str(message.get("role", "user"))
    content = message.get("content", "")
    if isinstance(content, str):
        return {"role": role, "content": [{"type": "input_text", "text": content}]}
    if not isinstance(content, list):
        raise BadRequestError("message content must be string or array")
    parts = []
    for item in content:
        if not isinstance(item, dict):
            raise BadRequestError("content items must be objects")
        item_type = item.get("type")
        if item_type == "text":
            parts.append({"type": "input_text", "text": str(item.get("text", ""))})
        elif item_type == "image_url":
            image_url = item.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else None
            if not url:
                raise BadRequestError("image_url content requires url")
            parts.append({"type": "input_image", "image_url": str(url)})
        else:
            raise UnsupportedFeatureError(f"unsupported xAI content part type '{item_type}'")
    return {"role": role, "content": parts}


def _translate_xai_responses_to_chat(data: dict[str, Any], model: str) -> dict[str, Any]:
    texts: list[str] = []
    for output in data.get("output", []):
        if output.get("type") == "message":
            for content in output.get("content", []):
                if content.get("type") == "output_text":
                    texts.append(str(content.get("text", "")))
    usage = data.get("usage", {}) if isinstance(data.get("usage"), dict) else {}
    return {
        "id": data.get("id", ""),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "".join(texts)},
                "finish_reason": "stop" if data.get("status") == "completed" else "length",
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {"error": response.text}


def _wait_for_http(url: str, timeout_sec: int) -> None:
    deadline = time.time() + timeout_sec
    with httpx.Client(timeout=2.0) as client:
        while time.time() < deadline:
            try:
                resp = client.get(url)
                if resp.status_code < 500:
                    return
            except Exception:
                pass
            time.sleep(0.5)
    raise RuntimeError(f"timeout waiting for local runtime at {url}")


def _check_http(url: str) -> bool:
    try:
        with httpx.Client(timeout=2.0) as client:
            return client.get(url).status_code < 500
    except Exception:
        return False


def _resolve_llama_server_bin() -> str:
    resolved = shutil.which("llama-server")
    if resolved:
        return resolved
    for candidate in ("/opt/homebrew/bin/llama-server", "/usr/local/bin/llama-server"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError(
        "llama-server not found in PATH; install llama.cpp or set PATH so launchd/systemd can resolve it"
    )


def _llama_runtime_port(public_port: int) -> int:
    if 61101 <= public_port <= 61199:
        return 61000 + (public_port - 61100)
    raise RuntimeError(
        f"llama route port {public_port} is outside the supported local-public range 61101-61199"
    )


def _validate_modalities(route: RouteConfig, body: dict[str, Any]) -> None:
    messages = body.get("messages", [])
    if not isinstance(messages, list):
        raise BadRequestError("messages must be an array")
    for message in messages:
        if not isinstance(message, dict):
            raise BadRequestError("messages entries must be objects")
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            item_type = part.get("type")
            if item_type == "image_url" and route.modalities.get("image_kb", 0) <= 0:
                raise UnsupportedFeatureError(f"image input unsupported on route {route.name}")
            if item_type == "video_url" and route.modalities.get("video_kb", 0) <= 0:
                raise UnsupportedFeatureError(f"video input unsupported on route {route.name}")
