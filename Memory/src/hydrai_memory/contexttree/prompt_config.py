"""Global summary config and local .PROMPT.json resolution for Hydrai ContexTree."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

DEFAULT_PROMPTS = {
    "text_summary": (
        "Summarize the following content. Aim for 10:1 compression with highly "
        "informative and compact words, keep at least 1-2 sentences for short "
        "content, while no more than 500 tokens for very long one."
    ),
    "folder_summary": (
        "Summarize this folder's contents. Write 1-2 sentences "
        "describing the folder's overall purpose."
    ),
    "image_summary": "Describe this image concisely.",
    "video_summary": "Describe this short video concisely.",
}

PROMPT_FILENAME = ".PROMPT.json"


@dataclass(frozen=True)
class SummaryBackendConfig:
    intelligence_base_url: str
    text_port: int
    image_port: int
    video_port: int
    embedder_port: int
    text_max_bytes: int
    image_max_bytes: int
    video_max_bytes: int
    prompts: dict[str, str]


def load_summary_config(path: str) -> SummaryBackendConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("ContexTree config must be a JSON object")

    intelligence = data.get("intelligence", {})
    if not isinstance(intelligence, dict):
        raise ValueError("ContexTree config.intelligence must be an object")
    base_url = str(intelligence.get("base_url", "http://127.0.0.1")).rstrip("/")
    if not base_url:
        raise ValueError("ContexTree config.intelligence.base_url is required")

    text_port = _require_port(intelligence, "text_port")
    image_port = _require_port(intelligence, "image_port")
    video_port = _require_port(intelligence, "video_port")
    embedder_port = _require_port(intelligence, "embedder_port")

    limits = data.get("limits", {})
    if limits is None:
        limits = {}
    if not isinstance(limits, dict):
        raise ValueError("ContexTree config.limits must be an object")

    prompts = dict(DEFAULT_PROMPTS)
    raw_prompts = data.get("prompts", {})
    if raw_prompts is not None:
        if not isinstance(raw_prompts, dict):
            raise ValueError("ContexTree config.prompts must be an object")
        for key, value in raw_prompts.items():
            if key in prompts and isinstance(value, str) and value.strip():
                prompts[key] = value.strip()

    return SummaryBackendConfig(
        intelligence_base_url=base_url,
        text_port=text_port,
        image_port=image_port,
        video_port=video_port,
        embedder_port=embedder_port,
        text_max_bytes=_limit_or_default(limits, "text_max_bytes", 65536),
        image_max_bytes=_limit_or_default(limits, "image_max_bytes", 1024 * 1024),
        video_max_bytes=_limit_or_default(limits, "video_max_bytes", 10 * 1024 * 1024),
        prompts=prompts,
    )


def resolve_local_prompt_overrides(root: str, dir_path: str) -> dict:
    root = os.path.realpath(root)
    dir_path = os.path.realpath(dir_path)
    try:
        if os.path.commonpath([root, dir_path]) != root:
            return {"prompts": {}, "ports": {}, "limits": {}}
    except ValueError:
        return {"prompts": {}, "ports": {}, "limits": {}}

    rel = os.path.relpath(dir_path, root)
    chain = [root]
    if rel != ".":
        current = root
        for part in rel.split(os.sep):
            current = os.path.join(current, part)
            chain.append(current)

    merged_prompts: dict[str, str] = {}
    merged_ports: dict[str, int] = {}
    merged_limits: dict[str, int] = {}
    for folder in chain:
        data = _load_local_prompt_file(os.path.join(folder, PROMPT_FILENAME))
        merged_prompts.update(data.get("prompts", {}))
        merged_ports.update(data.get("ports", {}))
        merged_limits.update(data.get("limits", {}))
    return {"prompts": merged_prompts, "ports": merged_ports, "limits": merged_limits}


def _load_local_prompt_file(path: str) -> dict:
    if not os.path.isfile(path):
        return {"prompts": {}, "ports": {}, "limits": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"prompts": {}, "ports": {}, "limits": {}}
    if not isinstance(data, dict):
        return {"prompts": {}, "ports": {}, "limits": {}}

    prompts: dict[str, str] = {}
    raw_prompts = data.get("prompts", {})
    if isinstance(raw_prompts, dict):
        for key, value in raw_prompts.items():
            if key in DEFAULT_PROMPTS and isinstance(value, str) and value.strip():
                prompts[key] = value.strip()

    ports: dict[str, int] = {}
    raw_ports = data.get("ports", {})
    if isinstance(raw_ports, dict):
        for key in ("text", "image", "video", "embedder"):
            value = raw_ports.get(key)
            if isinstance(value, int) and 1 <= value <= 65535:
                ports[key] = value
    limits: dict[str, int] = {}
    raw_limits = data.get("limits", {})
    if isinstance(raw_limits, dict):
        for key in ("text_max_bytes", "image_max_bytes", "video_max_bytes"):
            value = raw_limits.get(key)
            if isinstance(value, int) and value > 0:
                limits[key] = value

    return {"prompts": prompts, "ports": ports, "limits": limits}


def _require_port(section: dict, key: str) -> int:
    value = section.get(key)
    if not isinstance(value, int) or not (1 <= value <= 65535):
        raise ValueError(f"ContexTree config.intelligence.{key} must be an int port")
    return value


def _limit_or_default(section: dict, key: str, default: int) -> int:
    value = section.get(key, default)
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"ContexTree config.limits.{key} must be a positive int")
    return value
