"""System-space identity CRUD and compact Brain-facing identity APIs."""

from __future__ import annotations

import os
import shutil
from typing import Any

from hydrai_memory.contexttree.summary import load_summary
from hydrai_memory.identity_state.core import IdentityState, _validate_config_dict, _validate_token


class IdentityStore:
    """CRUD operations for normal identities within one sandbox."""

    def __init__(self, storage_root: str, sandbox_id: str, **identity_kwargs: Any):
        self.storage_root = os.path.realpath(storage_root)
        self.sandbox_id = _validate_token(sandbox_id, "sandbox_id")
        self.sandbox_root = os.path.join(self.storage_root, "sandboxes", self.sandbox_id)
        self.identities_root = os.path.join(self.storage_root, "sandboxes", self.sandbox_id, "identities")
        self.identity_kwargs = dict(identity_kwargs)
        os.makedirs(self.identities_root, exist_ok=True)
        os.makedirs(self._category_root("human"), exist_ok=True)
        os.makedirs(self._category_root("native"), exist_ok=True)

    def _category_root(self, category: str) -> str:
        return os.path.join(self.sandbox_root, category)

    def _identity_root(self, identity_id: str) -> str:
        return os.path.join(self.identities_root, _validate_token(identity_id, "identity_id"))

    def _light_root(self, category: str, identity_id: str) -> str:
        return os.path.join(
            self._category_root(category),
            _validate_token(identity_id, "identity_id"),
        )

    def _load_identity(self, identity_id: str) -> IdentityState:
        root = self._identity_root(identity_id)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"unknown identity: {identity_id}")
        return IdentityState(root, **self.identity_kwargs)

    def _summary(self, identity_id: str) -> dict[str, Any]:
        ident = self._load_identity(identity_id)
        return {
            "id": identity_id,
            "persona": ident.persona(),
            "soul": ident.soul(),
            "config": ident.config(),
        }

    def _light_summary(self, category: str, identity_id: str) -> dict[str, Any]:
        root = self._light_root(category, identity_id)
        persona_path = os.path.join(root, "PERSONA.md")
        if not os.path.isfile(persona_path):
            raise FileNotFoundError(f"unknown {category}: {identity_id}")
        try:
            with open(persona_path, "r", encoding="utf-8") as handle:
                persona = handle.read()
        except OSError:
            persona = ""
        return {"id": identity_id, "persona": persona}

    def _write_persona_file(self, root: str, content: str) -> None:
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, "PERSONA.md")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(str(content))
        os.replace(tmp, path)

    def _ensure_id_available(self, identity_id: str) -> None:
        identity_id = _validate_token(identity_id, "identity_id")
        if os.path.exists(self._identity_root(identity_id)):
            raise FileExistsError(f"identity already exists: {identity_id}")
        for category in ("human", "native"):
            if os.path.exists(self._light_root(category, identity_id)):
                raise FileExistsError(f"identity-like id already exists in {category}: {identity_id}")

    def get_identity_like_persona(self, identity_id: str) -> str:
        normal = self.get_identity(identity_id)
        if normal is not None:
            return str(normal.get("persona", "") or "")
        for category in ("human", "native"):
            root = self._light_root(category, identity_id)
            persona_path = os.path.join(root, "PERSONA.md")
            if not os.path.isfile(persona_path):
                continue
            try:
                with open(persona_path, "r", encoding="utf-8") as handle:
                    return handle.read()
            except OSError:
                return ""
        return ""

    def list_identities(self) -> list[dict[str, Any]]:
        try:
            entries = sorted(
                name for name in os.listdir(self.identities_root)
                if os.path.isdir(os.path.join(self.identities_root, name))
            )
        except OSError:
            return []
        return [self._summary(name) for name in entries]

    def create_identity(self, identity_id: str, persona: str, soul: str, config: dict[str, Any]) -> dict[str, Any]:
        identity_id = _validate_token(identity_id, "identity_id")
        if not isinstance(persona, str) or not persona:
            raise ValueError("persona must be a non-empty string")
        if not isinstance(soul, str) or not soul:
            raise ValueError("soul must be a non-empty string")
        _validate_config_dict(config)
        self._ensure_id_available(identity_id)
        root = self._identity_root(identity_id)
        ident = IdentityState.create(root, config=config, **self.identity_kwargs)
        ident.set_persona(persona)
        ident.set_soul(soul)
        ident.sync()
        return self._summary(identity_id)

    def get_identity(self, identity_id: str) -> dict[str, Any] | None:
        try:
            return self._summary(_validate_token(identity_id, "identity_id"))
        except FileNotFoundError:
            return None

    def delete_identity(self, identity_id: str) -> dict[str, Any] | None:
        item = self.get_identity(identity_id)
        if item is None:
            return None
        shutil.rmtree(self._identity_root(identity_id))
        return item

    def set_identity_persona(self, identity_id: str, content: str) -> dict[str, Any]:
        ident = self._load_identity(identity_id)
        ident.set_persona(str(content))
        ident.sync()
        return self._summary(identity_id)

    def set_identity_soul(self, identity_id: str, content: str) -> dict[str, Any]:
        ident = self._load_identity(identity_id)
        ident.set_soul(str(content))
        ident.sync()
        return self._summary(identity_id)

    def set_identity_config(self, identity_id: str, config: dict[str, Any]) -> dict[str, Any]:
        _validate_config_dict(config)
        ident = self._load_identity(identity_id)
        ident.set_config(config)
        return self._summary(identity_id)

    def list_humans(self) -> list[dict[str, Any]]:
        try:
            entries = sorted(
                name for name in os.listdir(self._category_root("human"))
                if os.path.isdir(os.path.join(self._category_root("human"), name))
            )
        except OSError:
            return []
        return [self._light_summary("human", name) for name in entries]

    def create_human(self, identity_id: str, persona: str) -> dict[str, Any]:
        identity_id = _validate_token(identity_id, "identity_id")
        if not isinstance(persona, str) or not persona:
            raise ValueError("persona must be a non-empty string")
        self._ensure_id_available(identity_id)
        self._write_persona_file(self._light_root("human", identity_id), persona)
        return self._light_summary("human", identity_id)

    def get_human(self, identity_id: str) -> dict[str, Any] | None:
        try:
            return self._light_summary("human", _validate_token(identity_id, "identity_id"))
        except FileNotFoundError:
            return None

    def delete_human(self, identity_id: str) -> dict[str, Any] | None:
        item = self.get_human(identity_id)
        if item is None:
            return None
        shutil.rmtree(self._light_root("human", identity_id))
        return item

    def set_human_persona(self, identity_id: str, content: str) -> dict[str, Any]:
        item = self.get_human(identity_id)
        if item is None:
            raise FileNotFoundError(f"unknown human: {identity_id}")
        self._write_persona_file(self._light_root("human", identity_id), content)
        return self._light_summary("human", identity_id)

    def list_native(self) -> list[dict[str, Any]]:
        try:
            entries = sorted(
                name for name in os.listdir(self._category_root("native"))
                if os.path.isdir(os.path.join(self._category_root("native"), name))
            )
        except OSError:
            return []
        return [self._light_summary("native", name) for name in entries]

    def get_native(self, identity_id: str) -> dict[str, Any] | None:
        try:
            return self._light_summary("native", _validate_token(identity_id, "identity_id"))
        except FileNotFoundError:
            return None


class IdentityBrainAPI:
    """Compact semantic identity APIs for Brain."""

    def __init__(self, store: IdentityStore):
        self.store = store

    def _load_identity(self, identity_id: str) -> IdentityState:
        return self.store._load_identity(identity_id)

    def _file_summaries(self, ident: IdentityState, folder: str) -> dict[str, str]:
        data = load_summary(os.path.join(ident.root, folder))
        files = data.get("files", {}) if isinstance(data, dict) else {}
        results: dict[str, str] = {}
        if not isinstance(files, dict):
            return results
        for name, entry in files.items():
            if not isinstance(name, str) or not name.endswith(".md"):
                continue
            summary = entry.get("text", "") if isinstance(entry, dict) else ""
            results[name.removesuffix(".md")] = summary if isinstance(summary, str) else ""
        return results

    def identity_profile(self, identity_id: str) -> dict[str, Any]:
        ident = self._load_identity(identity_id)
        friend_summaries = self._file_summaries(ident, "dynamics")
        session_summaries = self._file_summaries(ident, "ongoing")
        friends = [{"id": friend_id, "summary": friend_summaries.get(friend_id, "")} for friend_id in ident.get_friends()]
        sessions = [{"id": session_id, "summary": session_summaries.get(session_id, "")} for session_id in ident.get_sessions()]
        return {
            "persona": ident.persona(),
            "soul": ident.soul(),
            "self_dynamic": ident.dynamic("self"),
            "friends": friends,
            "sessions": sessions,
        }

    def identity_relations(self, identity_id: str, friend_ids: list[str]) -> dict[str, Any]:
        ident = self._load_identity(identity_id)
        persona_map: dict[str, str] = {}
        dynamic_map: dict[str, str] = {}
        for raw_id in friend_ids:
            try:
                friend_id = _validate_token(raw_id, "friend_id")
            except ValueError:
                continue
            try:
                dynamic_text = ident.dynamic(friend_id)
            except Exception:
                continue
            if not dynamic_text:
                continue
            dynamic_map[friend_id] = dynamic_text
            persona_text = self.store.get_identity_like_persona(friend_id)
            if persona_text:
                persona_map[friend_id] = persona_text
        return {"persona_map": persona_map, "dynamic_map": dynamic_map}

    def identity_sessions(self, identity_id: str, session_ids: list[str]) -> dict[str, Any]:
        ident = self._load_identity(identity_id)
        ongoing_map: dict[str, str] = {}
        for raw_id in session_ids:
            try:
                session_id = _validate_token(raw_id, "session_id")
            except ValueError:
                continue
            try:
                content = ident.ongoing(session_id)
            except Exception:
                continue
            if not content:
                continue
            ongoing_map[session_id] = content
        return {"ongoing_map": ongoing_map}

    def identity_memorables_search(
        self,
        identity_id: str,
        query: str,
        *,
        top_content_n: int,
        top_summary_k: int,
        min_score: float = 0.3,
    ) -> dict[str, Any]:
        ident = self._load_identity(identity_id)
        if not query or ident.embedder is None:
            return {"best_contents": [], "more_summaries": []}
        query_vec = ident.embed(str(query))
        if not query_vec:
            return {"best_contents": [], "more_summaries": []}
        raw = ident.search_by_embedding(query_vec, top_k=max(top_content_n + top_summary_k, 0), min_score=min_score, paths=["memorables"])
        hits = list(raw.get("results", []) or [])
        best_contents: list[dict[str, Any]] = []
        more_summaries: list[dict[str, Any]] = []
        content_hits = hits[: max(top_content_n, 0)]
        summary_hits = hits[max(top_content_n, 0) : max(top_content_n, 0) + max(top_summary_k, 0)]

        if content_hits:
            read_map = ident.read([str(item.get("path", "")) for item in content_hits if str(item.get("path", ""))])
        else:
            read_map = {}
        for item in content_hits:
            path = str(item.get("path", "") or "")
            best_contents.append(
                {
                    "name": os.path.basename(path),
                    "score": float(item.get("score", 0.0)),
                    "content": str(read_map.get(path, "") or ""),
                }
            )
        for item in summary_hits:
            path = str(item.get("path", "") or "")
            more_summaries.append(
                {
                    "name": os.path.basename(path),
                    "score": float(item.get("score", 0.0)),
                    "summary": str(item.get("summary", "") or ""),
                }
            )
        return {"best_contents": best_contents, "more_summaries": more_summaries}
