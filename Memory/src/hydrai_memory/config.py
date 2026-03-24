"""Config loading for the Memory service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SandboxConfig:
    sandbox_id: str
    port: int
    sandbox_space_root: str
    context_config_path: str


@dataclass(frozen=True)
class ServiceConfig:
    config_path: str
    storage_root: str
    control_port: int
    sandboxes: tuple[SandboxConfig, ...]


def _require_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0 or value > 65535:
        raise ValueError(f"{field_name} must be between 0 and 65535")
    return value


def _require_token(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    token = value.strip()
    if "/" in token or "\\" in token:
        raise ValueError(f"{field_name} must not contain path separators")
    return token


def load_config(path: str) -> ServiceConfig:
    config_path = os.path.realpath(path)
    with open(config_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("config root must be an object")

    storage_root = os.path.realpath(os.path.expanduser(str(data.get("storage_root") or "")))
    if not storage_root:
        raise ValueError("storage_root is required")
    control_port = _require_int(data.get("control_port"), "control_port")

    raw_sandboxes = data.get("sandboxes")
    if not isinstance(raw_sandboxes, list) or not raw_sandboxes:
        raise ValueError("sandboxes must be a non-empty list")

    seen_ids: set[str] = set()
    seen_ports: set[int] = set()
    if control_port != 0:
        seen_ports.add(control_port)
    sandboxes: list[SandboxConfig] = []
    for item in raw_sandboxes:
        if not isinstance(item, dict):
            raise ValueError("sandbox entries must be objects")
        sandbox_id = _require_token(item.get("id"), "sandbox.id")
        if sandbox_id in seen_ids:
            raise ValueError(f"duplicate sandbox id: {sandbox_id}")
        port = _require_int(item.get("port"), f"sandbox[{sandbox_id}].port")
        if port != 0 and port in seen_ports:
            raise ValueError(f"duplicate port: {port}")
        sandbox_space_root = os.path.realpath(os.path.expanduser(str(item.get("sandbox_space_root") or "")))
        context_config_path = os.path.realpath(os.path.expanduser(str(item.get("context_config_path") or ""))) if item.get("context_config_path") else ""
        sandboxes.append(
            SandboxConfig(
                sandbox_id=sandbox_id,
                port=port,
                sandbox_space_root=sandbox_space_root,
                context_config_path=context_config_path,
            )
        )
        seen_ids.add(sandbox_id)
        if port != 0:
            seen_ports.add(port)

    os.makedirs(storage_root, exist_ok=True)
    return ServiceConfig(
        config_path=config_path,
        storage_root=storage_root,
        control_port=control_port,
        sandboxes=tuple(sandboxes),
    )
