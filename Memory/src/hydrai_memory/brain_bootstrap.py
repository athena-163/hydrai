"""Deterministic Brain bootstrap assembly over Memory primitives."""

from __future__ import annotations

from typing import Any

from hydrai_memory.identity_state import IdentityBrainAPI, IdentityStore
from hydrai_memory.resources import ResourceRegistry
from hydrai_memory.sessionbook import SessionBrainAPI
from hydrai_memory.skillset import SkillManager


class BrainBootstrapAPI:
    """Compose deterministic bootstrap state for one Brain request."""

    def __init__(
        self,
        identity_store: IdentityStore,
        identity_brain: IdentityBrainAPI,
        session_brain: SessionBrainAPI,
        resource_registry: ResourceRegistry,
        skill_manager: SkillManager,
    ):
        self.identity_store = identity_store
        self.identity_brain = identity_brain
        self.session_brain = session_brain
        self.resource_registry = resource_registry
        self.skill_manager = skill_manager

    def _skill_shortlist(self, identity_id: str) -> list[dict[str, Any]]:
        listing = list(self.skill_manager.skill_list(identity_id).get("results", []) or [])
        results: list[dict[str, Any]] = []
        for item in listing:
            if str(item.get("category") or "") != "shortlist":
                continue
            name = str(item.get("name") or "")
            read_back = self.skill_manager.skill_read(identity_id, name, category="shortlist")
            entries = list(read_back.get("results", []) or [])
            if not entries:
                continue
            prompt_text = str(entries[0].get("prompt_text") or "")
            results.append(
                {
                    "name": name,
                    "category": "shortlist",
                    "path": str(item.get("path") or ""),
                    "summary": str(item.get("summary") or ""),
                    "prompt_text": prompt_text,
                }
            )
        return results

    def bootstrap(
        self,
        identity_id: str,
        *,
        requestor_id: str,
        session_id: str = "",
        query: str = "",
        top_k: int = 10,
        min_score: float = 0.3,
        attachment_limit: int = 5,
    ) -> dict[str, Any]:
        profile = self.identity_brain.identity_profile(identity_id)
        friend_ids = [str(item.get("id") or "") for item in list(profile.get("friends", []) or []) if str(item.get("id") or "")]
        session_ids = [str(item.get("id") or "") for item in list(profile.get("sessions", []) or []) if str(item.get("id") or "")]

        requestor_persona = self.identity_store.get_identity_like_persona(requestor_id)
        shortlist = self._skill_shortlist(identity_id)

        session: dict[str, Any] | None = None
        if str(session_id or "").strip():
            recent = self.session_brain.session_recent(str(session_id))
            mounted_ids = sorted(dict(recent.get("resources", {}) or {}).keys())
            mounted_resources = []
            resource_map = self.resource_registry.resource_map_for_brain(mounted_ids)
            for resource_id in mounted_ids:
                item = resource_map.get(resource_id, {})
                mounted_resources.append(
                    {
                        "id": resource_id,
                        "summary": str(item.get("summary") or ""),
                        "type": str(item.get("type") or ""),
                    }
                )
            latest_attachments = self.session_brain.session_latest_attachments(str(session_id), limit=attachment_limit)
            search_hits = (
                self.session_brain.session_search_text(
                    str(session_id),
                    str(query or ""),
                    top_k=top_k,
                    min_score=min_score,
                )
                if str(query or "").strip()
                else {"results": [], "checked": 0, "missing": 0}
            )
            session = {
                "id": str(session_id),
                "context": str(recent.get("context") or ""),
                "summary": str(recent.get("summary") or ""),
                "participants": dict(recent.get("identities") or {}),
                "resources": dict(recent.get("resources") or {}),
                "mounted_resources": mounted_resources,
                "latest_attachments": latest_attachments,
                "search": search_hits,
            }

        return {
            "target_identity_id": str(identity_id),
            "requestor_id": str(requestor_id),
            "requestor_persona": requestor_persona,
            "target_profile": profile,
            "friend_ids": friend_ids,
            "session_ids": session_ids,
            "session": session,
            "skill_shortlist": shortlist,
        }
