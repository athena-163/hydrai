"""Config loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """Raised when config is invalid."""


@dataclass(frozen=True)
class Limits:
    max_concurrency: int
    timeout_sec: int


@dataclass(frozen=True)
class RouteConfig:
    name: str
    type: str
    adapter: str
    listen: int
    runtime_port: int
    model: str
    limits: Limits
    target: str = ""
    key_env: str = ""
    artifact: str = ""
    mmproj: str = ""
    think: tuple[str, ...] = ()
    modalities: dict[str, int] = field(default_factory=dict)
    search: bool = False
    context_k: int = 0
    extra_params: dict = field(default_factory=dict)
    output_dimension: int = 0
    output_encoding: str = ""


@dataclass(frozen=True)
class ServiceConfig:
    control_port: int
    routes: tuple[RouteConfig, ...]
    config_path: str = ""


def load_config(path: str | Path) -> ServiceConfig:
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid json in config: {path}") from exc

    if not isinstance(data, dict):
        raise ConfigError("top-level config must be an object")
    control_port = data.get("control_port", 61000)
    if not isinstance(control_port, int) or control_port < 1024 or control_port > 65535:
        raise ConfigError("'control_port' must be an int in 1024-65535")
    routes = data.get("routes")
    if not isinstance(routes, list) or not routes:
        raise ConfigError("'routes' must be a non-empty array")
    validated: list[RouteConfig] = []
    seen_ports: set[int] = {control_port}
    for idx, raw in enumerate(routes):
        validated.append(_validate_route(raw, idx, seen_ports))
    return ServiceConfig(control_port=control_port, routes=tuple(validated), config_path=str(path))


def _validate_route(raw: object, idx: int, seen_ports: set[int]) -> RouteConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"route {idx}: must be an object")
    name = _required_str(raw, "name", idx)
    route_type = _required_str(raw, "type", idx)
    if route_type not in {"chat", "embedding"}:
        raise ConfigError(f"route {idx}: unsupported type '{route_type}'")
    adapter = _required_str(raw, "adapter", idx)
    if adapter not in {"remote", "llama", "embedding"}:
        raise ConfigError(f"route {idx}: unsupported adapter '{adapter}'")
    listen = _required_int(raw, "listen", idx)
    if listen < 1024 or listen > 65535 or listen in seen_ports:
        raise ConfigError(f"route {idx}: invalid or duplicate listen port {listen}")
    seen_ports.add(listen)
    model = _required_str(raw, "model", idx)

    limits_raw = raw.get("limits")
    if not isinstance(limits_raw, dict):
        raise ConfigError(f"route {idx}: 'limits' must be an object")
    max_concurrency = int(limits_raw.get("max_concurrency", 1))
    timeout_sec = int(limits_raw.get("timeout_sec", 120))
    if max_concurrency < 1:
        raise ConfigError(f"route {idx}: max_concurrency must be >= 1")
    if timeout_sec < 1:
        raise ConfigError(f"route {idx}: timeout_sec must be >= 1")
    limits = Limits(max_concurrency=max_concurrency, timeout_sec=timeout_sec)

    think = raw.get("think", [])
    if not isinstance(think, list) or any(v not in {"off", "low", "mid", "high"} for v in think):
        raise ConfigError(f"route {idx}: think must be an array of off/low/mid/high")
    modalities = raw.get("modalities", {})
    if not isinstance(modalities, dict):
        raise ConfigError(f"route {idx}: modalities must be an object")
    clean_modalities = {}
    for key, value in modalities.items():
        if not isinstance(value, int) or value < 0:
            raise ConfigError(f"route {idx}: modality limit '{key}' must be a non-negative int")
        clean_modalities[str(key)] = value

    route = RouteConfig(
        name=name,
        type=route_type,
        adapter=adapter,
        listen=listen,
        runtime_port=int(raw.get("runtime_port", 0) or 0),
        model=model,
        target=str(raw.get("target", "")),
        key_env=str(raw.get("key_env", "")),
        artifact=str(raw.get("artifact", "")),
        mmproj=str(raw.get("mmproj", "")),
        think=tuple(think),
        modalities=clean_modalities,
        search=bool(raw.get("search", False)),
        context_k=int(raw.get("context_k", 0) or 0),
        limits=limits,
        extra_params=raw.get("extra_params", {}) if isinstance(raw.get("extra_params", {}), dict) else {},
        output_dimension=int(raw.get("output_dimension", 0) or 0),
        output_encoding=str(raw.get("output_encoding", "")),
    )

    if route.adapter == "remote":
        if route.type != "chat":
            raise ConfigError(f"route {idx}: remote adapter requires type=chat")
        if not route.target.startswith(("http://", "https://")):
            raise ConfigError(f"route {idx}: remote route requires valid target")
    elif route.adapter == "llama":
        if route.type != "chat":
            raise ConfigError(f"route {idx}: llama adapter requires type=chat")
        if not route.artifact:
            raise ConfigError(f"route {idx}: llama route requires artifact")
        if route.runtime_port < 1024 or route.runtime_port > 65535 or route.runtime_port in seen_ports:
            raise ConfigError(f"route {idx}: llama route requires unique runtime_port in 1024-65535")
        seen_ports.add(route.runtime_port)
    elif route.adapter == "embedding":
        if route.type != "embedding":
            raise ConfigError(f"route {idx}: embedding adapter requires type=embedding")
        if route.output_encoding and route.output_encoding != "base64":
            raise ConfigError(f"route {idx}: only base64 output_encoding is supported")
    return route


def _required_str(raw: dict, key: str, idx: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"route {idx}: '{key}' must be a non-empty string")
    return value.strip()


def _required_int(raw: dict, key: str, idx: int) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise ConfigError(f"route {idx}: '{key}' must be an int")
    return value
