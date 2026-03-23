"""Sandbox-scoped Memory APIs for Brain-facing resource access."""

from __future__ import annotations

import os
from typing import Any

from hydrai_memory.contexttree import ContexTree, Embedder
from hydrai_memory.identity_state import IdentityState
from hydrai_memory.resources.core import ResourceRegistry
from hydrai_memory.sessionbook import SessionBook


def _validate_token(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if "/" in value or "\\" in value:
        raise ValueError(f"{field_name} must not contain path separators")
    return value.strip()


def _path_within(base: str, target: str) -> bool:
    base_real = os.path.realpath(base)
    target_real = os.path.realpath(target)
    try:
        common = os.path.commonpath([base_real, target_real])
    except ValueError:
        return False
    return common == base_real


class MemorySandboxAPI:
    """Generic file-tree APIs over one sandbox's resources, identities, and sessions."""

    def __init__(
        self,
        storage_root: str,
        sandbox_id: str,
        *,
        sandbox_space_root: str = "",
        system_access: bool = False,
        embedder: Embedder | None = None,
        config_path: str | None = None,
    ):
        self.storage_root = os.path.realpath(storage_root)
        self.sandbox_id = _validate_token(sandbox_id, "sandbox_id")
        self.sandbox_root = os.path.join(self.storage_root, "sandboxes", self.sandbox_id)
        self.sandbox_space_root = os.path.realpath(sandbox_space_root) if sandbox_space_root else ""
        self.system_access = bool(system_access)
        self.embedder = embedder
        self.config_path = os.path.realpath(config_path) if config_path else None
        self.registry = ResourceRegistry(self.sandbox_root)

    def _identity_root(self, category: str, identity_id: str) -> str:
        return os.path.join(self.sandbox_root, category, _validate_token(identity_id, "identity_id"))

    def _session_root(self, session_id: str) -> str:
        return os.path.join(self.sandbox_root, "sessions", _validate_token(session_id, "session_id"))

    def _ensure_brain_can_access_path(self, path: str) -> None:
        if self.system_access:
            return
        if _path_within(self.sandbox_root, path):
            return
        if self.sandbox_space_root and _path_within(self.sandbox_space_root, path):
            return
        raise PermissionError(f"path outside sandbox boundary: {path}")

    def _resource_tree(self, resource_id: str) -> ContexTree:
        item = self.registry.get_resource(_validate_token(resource_id, "resource_id"))
        if item is None:
            raise KeyError(f"unknown resource: {resource_id}")
        if item["type"] != "context_tree":
            raise ValueError(f"resource type unsupported for tree access: {item['type']}")
        self._ensure_brain_can_access_path(item["root"])
        return ContexTree(item["root"], config_path=item.get("config_path") or self.config_path, embedder=self.embedder)

    def _identity_tree(self, category: str, identity_id: str) -> IdentityState:
        root = self._identity_root(category, identity_id)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"{category} not found: {identity_id}")
        self._ensure_brain_can_access_path(root)
        return IdentityState(root, embedder=self.embedder, config_path=self.config_path)

    def _session_tree(self, session_id: str) -> ContexTree:
        root = self._session_root(session_id)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"session not found: {session_id}")
        self._ensure_brain_can_access_path(root)
        return SessionBook(root, embedder=self.embedder, config_path=self.config_path).tree

    def _resolve_tree(self, target_type: str, target_id: str) -> ContexTree:
        kind = str(target_type or "").strip().lower()
        if kind == "resource":
            return self._resource_tree(target_id)
        if kind == "identity":
            return self._identity_tree("identities", target_id)
        if kind == "human":
            return self._identity_tree("human", target_id)
        if kind == "native":
            return self._identity_tree("native", target_id)
        if kind == "session":
            return self._session_tree(target_id)
        raise ValueError(f"unsupported target_type: {target_type}")

    def view(
        self,
        *,
        target_type: str,
        target_id: str,
        path: str = "",
        depth: int = 2,
        summary_depth: int = 1,
    ) -> list[dict]:
        return self._resolve_tree(target_type, target_id).view(path=path, depth=depth, summary_depth=summary_depth)

    def read(self, *, target_type: str, target_id: str, paths: list[str]) -> dict[str, Any]:
        return self._resolve_tree(target_type, target_id).read(paths)

    def search(
        self,
        *,
        target_type: str,
        target_id: str,
        query_text: str | None = None,
        query_embed: str | None = None,
        top_k: int = 10,
        min_score: float = 0.3,
        paths: list[str] | None = None,
    ) -> dict[str, Any]:
        tree = self._resolve_tree(target_type, target_id)
        if query_embed is not None:
            return tree.search_by_embedding(query_embed, top_k=top_k, min_score=min_score, paths=paths)
        if query_text is not None:
            return tree.search_by_text(query_text, top_k=top_k, min_score=min_score, paths=paths)
        raise ValueError("search requires query_text or query_embed")

    def write(
        self,
        *,
        target_type: str,
        target_id: str,
        path: str,
        content: str,
        summary: str = "",
    ) -> dict[str, Any]:
        self._resolve_tree(target_type, target_id).write_text(path, content, summary=summary)
        return {"ok": True, "path": path}

    def append(
        self,
        *,
        target_type: str,
        target_id: str,
        path: str,
        content: str,
        summary: str = "",
    ) -> dict[str, Any]:
        self._resolve_tree(target_type, target_id).append_text(path, content, summary=summary)
        return {"ok": True, "path": path}

    def delete(self, *, target_type: str, target_id: str, path: str) -> dict[str, Any]:
        self._resolve_tree(target_type, target_id).delete(path)
        return {"ok": True, "path": path}
