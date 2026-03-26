"""Centralized sandbox access and skill visibility policy."""

from __future__ import annotations

import os
from typing import Any

from hydrai_memory.identity_state import IdentityStore
from hydrai_memory.resources.core import ResourceRegistry
from hydrai_memory.sessionbook import SessionBook


def _validate_token(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    token = value.strip()
    if "/" in token or "\\" in token:
        raise ValueError(f"{field_name} must not contain path separators")
    return token


class SandboxPolicy:
    def __init__(
        self,
        storage_root: str,
        sandbox_id: str,
        *,
        sandbox_skill_whitelist: tuple[str, ...] = (),
        sandbox_skill_blacklist: tuple[str, ...] = (),
    ):
        self.storage_root = os.path.realpath(storage_root)
        self.sandbox_id = _validate_token(sandbox_id, "sandbox_id")
        self.sandbox_root = os.path.join(self.storage_root, "sandboxes", self.sandbox_id)
        self.sandbox_skill_whitelist = {str(item) for item in sandbox_skill_whitelist if str(item)}
        self.sandbox_skill_blacklist = {str(item) for item in sandbox_skill_blacklist if str(item)}

    def _session_root(self, session_id: str) -> str:
        return os.path.join(self.sandbox_root, "sessions", _validate_token(session_id, "session_id"))

    def identity_like_exists(self, identity_id: str) -> bool:
        token = _validate_token(identity_id, "identity_id")
        return any(
            os.path.isdir(os.path.join(self.sandbox_root, category, token))
            for category in ("identities", "human", "native")
        )

    def load_session_config(
        self,
        session_id: str,
        *,
        embedder: Any = None,
        config_path: str | None = None,
    ) -> dict[str, Any]:
        root = self._session_root(session_id)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"session not found: {session_id}")
        return SessionBook(root, embedder=embedder, config_path=config_path).config()

    def session_identity_mode(
        self,
        session_id: str,
        actor_identity_id: str,
        *,
        embedder: Any = None,
        config_path: str | None = None,
    ) -> str:
        cfg = self.load_session_config(session_id, embedder=embedder, config_path=config_path)
        identities = cfg.get("identities", {})
        if not isinstance(identities, dict):
            return ""
        mode = identities.get(actor_identity_id, "")
        return str(mode) if isinstance(mode, str) else ""

    def session_resource_mode(
        self,
        session_id: str,
        resource_id: str,
        *,
        embedder: Any = None,
        config_path: str | None = None,
    ) -> str:
        cfg = self.load_session_config(session_id, embedder=embedder, config_path=config_path)
        resources = cfg.get("resources", {})
        if not isinstance(resources, dict):
            return ""
        mode = resources.get(resource_id, "")
        return str(mode) if isinstance(mode, str) else ""

    def authorize_tree(
        self,
        *,
        target_type: str,
        target_id: str,
        actor_identity_id: str,
        session_id: str = "",
        write: bool = False,
        system_access: bool = False,
        embedder: Any = None,
        config_path: str | None = None,
    ) -> None:
        if system_access:
            return
        actor = _validate_token(actor_identity_id, "actor_identity_id")
        if not self.identity_like_exists(actor):
            raise FileNotFoundError(f"unknown actor identity: {actor}")
        kind = str(target_type or "").strip().lower()
        if kind in {"identity", "human", "native"}:
            if actor != _validate_token(target_id, "target_id"):
                raise PermissionError("actor may only access its own identity-like tree")
            return
        if kind == "session":
            mode = self.session_identity_mode(target_id, actor, embedder=embedder, config_path=config_path)
            if mode not in {"ro", "rw"}:
                raise PermissionError("actor is not a participant in session")
            if write and mode != "rw":
                raise PermissionError("actor does not have write access to session")
            return
        if kind == "resource":
            session_token = _validate_token(session_id, "session_id")
            actor_mode = self.session_identity_mode(session_token, actor, embedder=embedder, config_path=config_path)
            if actor_mode not in {"ro", "rw"}:
                raise PermissionError("actor is not a participant in session")
            resource_mode = self.session_resource_mode(session_token, target_id, embedder=embedder, config_path=config_path)
            if resource_mode not in {"ro", "rw"}:
                raise PermissionError("resource is not mounted in session")
            if write and (actor_mode != "rw" or resource_mode != "rw"):
                raise PermissionError("actor does not have write access to resource")
            return
        raise ValueError(f"unsupported target_type: {target_type}")

    def list_accessible_resources(
        self,
        *,
        actor_identity_id: str,
        session_id: str,
        registry: ResourceRegistry,
        embedder: Any = None,
        config_path: str | None = None,
        system_access: bool = False,
    ) -> dict[str, Any]:
        self.authorize_tree(
            target_type="session",
            target_id=session_id,
            actor_identity_id=actor_identity_id,
            system_access=system_access,
            embedder=embedder,
            config_path=config_path,
        )
        cfg = self.load_session_config(session_id, embedder=embedder, config_path=config_path)
        resources = cfg.get("resources", {})
        if not isinstance(resources, dict):
            resources = {}
        mapping = registry.resource_map_for_brain(sorted(resources.keys()))
        results: list[dict[str, Any]] = []
        for resource_id in sorted(resources.keys()):
            mode = str(resources.get(resource_id) or "")
            item = mapping.get(resource_id, {})
            results.append(
                {
                    "id": resource_id,
                    "mode": mode,
                    "type": str(item.get("type") or ""),
                    "summary": str(item.get("summary") or ""),
                }
            )
        return {"results": results}

    def effective_skill_policy(self, identity_store: IdentityStore, identity_id: str) -> tuple[set[str], set[str]]:
        identity_whitelist: set[str] = set()
        identity_blacklist: set[str] = set()
        identity = identity_store.get_identity(identity_id)
        if identity is not None:
            config = dict(identity.get("config") or {})
            skills_cfg = dict(config.get("skills") or {}) if isinstance(config.get("skills"), dict) else {}
            identity_whitelist = {str(item) for item in list(skills_cfg.get("whitelist") or []) if str(item)}
            identity_blacklist = {str(item) for item in list(skills_cfg.get("blacklist") or []) if str(item)}

        whitelist = set(self.sandbox_skill_whitelist)
        if whitelist and identity_whitelist:
            whitelist &= identity_whitelist
        elif identity_whitelist:
            whitelist = set(identity_whitelist)
        blacklist = set(self.sandbox_skill_blacklist) | set(identity_blacklist)
        return whitelist, blacklist

    def skill_allowed(self, identity_store: IdentityStore, identity_id: str, skill_name: str) -> bool:
        name = str(skill_name or "").strip()
        if not name:
            return False
        whitelist, blacklist = self.effective_skill_policy(identity_store, identity_id)
        if whitelist and name not in whitelist:
            return False
        if name in blacklist:
            return False
        return True

    def capability_allowed(self, identity_store: IdentityStore, identity_id: str, capability_name: str) -> bool:
        name = str(capability_name or "").strip()
        if not name:
            return False
        whitelist, blacklist = self.effective_skill_policy(identity_store, identity_id)
        if name in blacklist:
            return False
        return name in whitelist
