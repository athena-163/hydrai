"""System-space session CRUD and compact Brain-facing session APIs."""

from __future__ import annotations

import os
import shutil
from typing import Any

from hydrai_memory.contexttree import ContexTree
from hydrai_memory.identity_state.core import _validate_token
from hydrai_memory.identity_state.manager import IdentityStore
from hydrai_memory.resources import ResourceRegistry
from hydrai_memory.sessionbook.core import SessionBook, _validate_mode


class SessionStore:
    """CRUD operations for sandbox-local sessions."""

    def __init__(self, storage_root: str, sandbox_id: str, **session_kwargs: Any):
        self.storage_root = os.path.realpath(storage_root)
        self.sandbox_id = _validate_token(sandbox_id, "sandbox_id")
        self.sandbox_root = os.path.join(self.storage_root, "sandboxes", self.sandbox_id)
        self.sessions_root = os.path.join(self.sandbox_root, "sessions")
        self.session_kwargs = dict(session_kwargs)
        self.identity_store = IdentityStore(storage_root, sandbox_id, **session_kwargs)
        self.resource_registry = ResourceRegistry(self.sandbox_root)
        os.makedirs(self.sessions_root, exist_ok=True)

    def _session_root(self, session_id: str) -> str:
        return os.path.join(self.sessions_root, _validate_token(session_id, "session_id"))

    def _load_session(self, session_id: str) -> SessionBook:
        root = self._session_root(session_id)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"unknown session: {session_id}")
        return SessionBook(root, **self.session_kwargs)

    def _identity_like_exists(self, identity_id: str) -> bool:
        return (
            self.identity_store.get_identity(identity_id) is not None
            or self.identity_store.get_human(identity_id) is not None
            or self.identity_store.get_native(identity_id) is not None
        )

    def _validate_identities_map(self, identities: dict[str, str]) -> dict[str, str]:
        if not isinstance(identities, dict):
            raise ValueError("identities must be a JSON object")
        normalized: dict[str, str] = {}
        for raw_id, raw_mode in identities.items():
            identity_id = _validate_token(raw_id, "identity_id")
            mode = _validate_mode(str(raw_mode))
            if not self._identity_like_exists(identity_id):
                raise FileNotFoundError(f"unknown identity-like participant: {identity_id}")
            normalized[identity_id] = mode
        return normalized

    def _validate_resources_map(self, resources: dict[str, str]) -> dict[str, str]:
        if not isinstance(resources, dict):
            raise ValueError("resources must be a JSON object")
        normalized: dict[str, str] = {}
        for raw_id, raw_mode in resources.items():
            resource_id = _validate_token(raw_id, "resource_id")
            mode = _validate_mode(str(raw_mode))
            if self.resource_registry.get_resource(resource_id) is None:
                raise FileNotFoundError(f"unknown mounted resource: {resource_id}")
            normalized[resource_id] = mode
        return normalized

    def _summary(self, session_id: str) -> dict[str, Any]:
        book = self._load_session(session_id)
        cfg = book.config()
        return {
            "id": session_id,
            "channel": str(cfg.get("channel", "") or ""),
            "identities": dict(cfg.get("identities", {}) or {}),
            "resources": dict(cfg.get("resources", {}) or {}),
            "brain": dict(cfg.get("brain", {}) or {}),
            "limits": dict(cfg.get("limits", {}) or {}),
            "attachments": dict(cfg.get("attachments", {}) or {}),
            "summary": book.tree.folder_summary(),
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        try:
            entries = sorted(
                name for name in os.listdir(self.sessions_root)
                if os.path.isdir(os.path.join(self.sessions_root, name))
            )
        except OSError:
            return []
        return [self._summary(name) for name in entries]

    def create_session(
        self,
        session_id: str,
        identities: dict[str, str],
        resources: dict[str, str],
        *,
        channel: str = "",
        brain: dict[str, Any] | None = None,
        limits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = _validate_token(session_id, "session_id")
        identities_map = self._validate_identities_map(identities)
        resources_map = self._validate_resources_map(resources)
        if os.path.exists(self._session_root(session_id)):
            raise FileExistsError(f"session already exists: {session_id}")
        config = {
            "channel": str(channel or ""),
            "identities": identities_map,
            "resources": resources_map,
            "brain": dict(brain or {}),
            "attachments": {"next_serial": 1},
            "limits": dict(limits or {}),
        }
        SessionBook.create(self._session_root(session_id), config=config, **self.session_kwargs)
        return self._summary(session_id)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        try:
            return self._summary(_validate_token(session_id, "session_id"))
        except FileNotFoundError:
            return None

    def delete_session(self, session_id: str) -> dict[str, Any] | None:
        item = self.get_session(session_id)
        if item is None:
            return None
        shutil.rmtree(self._session_root(session_id))
        return item

    def invite_identity(self, session_id: str, identity_id: str, mode: str = "rw") -> dict[str, Any]:
        identity_id = _validate_token(identity_id, "identity_id")
        _validate_mode(mode)
        if not self._identity_like_exists(identity_id):
            raise FileNotFoundError(f"unknown identity-like participant: {identity_id}")
        book = self._load_session(session_id)
        book.invite(identity_id, mode)
        return self._summary(session_id)

    def kick_identity(self, session_id: str, identity_id: str) -> dict[str, Any]:
        book = self._load_session(session_id)
        book.kick(_validate_token(identity_id, "identity_id"))
        return self._summary(session_id)

    def mount_resource(self, session_id: str, resource_id: str, mode: str = "rw") -> dict[str, Any]:
        resource_id = _validate_token(resource_id, "resource_id")
        _validate_mode(mode)
        if self.resource_registry.get_resource(resource_id) is None:
            raise FileNotFoundError(f"unknown mounted resource: {resource_id}")
        book = self._load_session(session_id)
        book.mount(resource_id, mode)
        return self._summary(session_id)

    def unmount_resource(self, session_id: str, resource_id: str) -> dict[str, Any]:
        book = self._load_session(session_id)
        book.unmount(_validate_token(resource_id, "resource_id"))
        return self._summary(session_id)

    def attach_file(self, session_id: str, source_path: str, sender: str, summary: str = "") -> dict[str, Any]:
        sender = _validate_token(sender, "sender")
        if not self._identity_like_exists(sender):
            raise FileNotFoundError(f"unknown identity-like participant: {sender}")
        book = self._load_session(session_id)
        tag = book.attach(source_path, sender, summary=summary)
        info = book.attachment_info([tag])
        return info[0] if info else {"tag": tag, "path": "", "summary": ""}

    def append_turn(self, session_id: str, text: str) -> dict[str, Any]:
        book = self._load_session(session_id)
        book.append(str(text))
        return self._summary(session_id)

    def break_chapter(self, session_id: str) -> dict[str, Any]:
        book = self._load_session(session_id)
        return {"ok": bool(book.end_chapter())}


class SessionBrainAPI:
    """Compact session APIs for Brain."""

    def __init__(self, store: SessionStore):
        self.store = store

    def _load_session(self, session_id: str) -> SessionBook:
        return self.store._load_session(session_id)

    def _query_vec(self, book: SessionBook, query: str) -> str:
        text = str(query or "").strip()
        if not text:
            return ""
        return book.tree.embed(text)

    def session_recent(
        self,
        session_id: str,
        *,
        query: str = "",
        top_k: int = 10,
        min_score: float = 0.3,
    ) -> dict[str, Any]:
        book = self._load_session(session_id)
        query_vec = self._query_vec(book, query)
        if not query_vec:
            return book.query()
        return book.query(query_embed=query_vec, top_k=top_k, min_score=min_score)

    def session_search_text(
        self,
        session_id: str,
        query: str,
        *,
        top_k: int = 10,
        min_score: float = 0.3,
    ) -> dict[str, Any]:
        book = self._load_session(session_id)
        query_vec = self._query_vec(book, query)
        if not query_vec:
            return {"results": [], "checked": 0, "missing": 0}

        results: list[dict[str, Any]] = []
        checked = 0
        missing = 0

        session_hits = book.tree.search_by_embedding(query_vec, top_k=top_k, min_score=min_score)
        checked += int(session_hits.get("checked", 0) or 0)
        missing += int(session_hits.get("missing", 0) or 0)
        for item in list(session_hits.get("results", []) or []):
            hit = dict(item)
            hit["source_type"] = "session"
            hit["source_id"] = session_id
            results.append(hit)

        cfg = book.config()
        for resource_id in sorted(dict(cfg.get("resources", {}) or {}).keys()):
            resource = self.store.resource_registry.get_resource(resource_id)
            if resource is None or resource.get("type") != "context_tree":
                continue
            tree = ContexTree(
                str(resource.get("root") or ""),
                config_path=str(resource.get("config_path") or "") or None,
                embedder=book.embedder,
            )
            resource_hits = tree.search_by_embedding(query_vec, top_k=top_k, min_score=min_score)
            checked += int(resource_hits.get("checked", 0) or 0)
            missing += int(resource_hits.get("missing", 0) or 0)
            for item in list(resource_hits.get("results", []) or []):
                hit = dict(item)
                hit["source_type"] = "resource"
                hit["source_id"] = resource_id
                results.append(hit)

        results.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return {"results": results[:top_k], "checked": checked, "missing": missing}

    def session_latest_attachments(self, session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        book = self._load_session(session_id)
        return book.latest_attachments(limit=limit)
