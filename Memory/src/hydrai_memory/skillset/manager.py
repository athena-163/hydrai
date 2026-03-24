"""Skill management and Brain-facing skill APIs."""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Any

from hydrai_memory.identity_state import IdentityStore
from hydrai_memory.skillset.core import SkillSet


@dataclass(frozen=True)
class TrustedSkillHub:
    hub_id: str
    index_url: str
    site_url: str = ""
    description: str = ""


def _validate_token(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    token = value.strip()
    if "/" in token or "\\" in token:
        raise ValueError(f"{field_name} must not contain path separators")
    return token


class SkillManager:
    """Skill discovery, rendering, and trusted install flows."""

    def __init__(
        self,
        storage_root: str,
        sandbox_id: str,
        *,
        trusted_hubs: tuple[TrustedSkillHub, ...] = (),
        config_path: str | None = None,
    ):
        self.storage_root = os.path.realpath(storage_root)
        self.sandbox_id = _validate_token(sandbox_id, "sandbox_id")
        self.skills_root = os.path.join(self.storage_root, "skills")
        self.shortlist_root = os.path.join(self.skills_root, "shortlist")
        self.builtin_root = os.path.join(self.skills_root, "builtin")
        self.user_root = os.path.join(self.skills_root, "user")
        self.skillset = SkillSet(config_path=config_path)
        self.identity_store = IdentityStore(storage_root, sandbox_id, config_path=config_path)
        self.trusted_hubs = tuple(trusted_hubs)
        os.makedirs(self.skills_root, exist_ok=True)

    def initialize_defaults(self) -> dict[str, Any]:
        result = self.skillset.initialize(self.skills_root, categories=("shortlist", "builtin"))
        os.makedirs(self.user_root, exist_ok=True)
        return result

    def list_trusted_sites(self) -> list[dict[str, str]]:
        return [
            {
                "id": hub.hub_id,
                "index_url": hub.index_url,
                "site_url": hub.site_url,
                "description": hub.description,
            }
            for hub in self.trusted_hubs
        ]

    def _skill_policy(self, identity_id: str) -> tuple[set[str], set[str]]:
        identity = self.identity_store.get_identity(identity_id)
        if identity is None:
            raise FileNotFoundError(f"unknown identity: {identity_id}")
        config = dict(identity.get("config") or {})
        skills_cfg = dict(config.get("skills") or {}) if isinstance(config.get("skills"), dict) else {}
        whitelist = {str(item) for item in list(skills_cfg.get("whitelist") or []) if str(item)}
        blacklist = {str(item) for item in list(skills_cfg.get("blacklist") or []) if str(item)}
        return whitelist, blacklist

    def _is_visible(self, name: str, whitelist: set[str], blacklist: set[str]) -> bool:
        if whitelist and name not in whitelist:
            return False
        if name in blacklist:
            return False
        return True

    def _list_category(self, category: str) -> list[dict[str, Any]]:
        root = os.path.join(self.skills_root, category)
        if not os.path.isdir(root):
            return []
        items = self.skillset.list_skills(root)
        return [{**item, "category": category} for item in items]

    def skill_list(self, identity_id: str) -> dict[str, Any]:
        whitelist, blacklist = self._skill_policy(identity_id)
        results: list[dict[str, Any]] = []
        for category in ("shortlist", "builtin", "user"):
            for item in self._list_category(category):
                if self._is_visible(str(item.get("name") or ""), whitelist, blacklist):
                    results.append(item)
        return {"results": results}

    def skill_search(self, identity_id: str, query: str, *, limit: int = 10, min_score: float = 0.3) -> dict[str, Any]:
        whitelist, blacklist = self._skill_policy(identity_id)
        hits: list[dict[str, Any]] = []
        for category in ("shortlist", "builtin", "user"):
            root = os.path.join(self.skills_root, category)
            if not os.path.isdir(root):
                continue
            for item in self.skillset.search_skills(root, query, limit=limit, min_score=min_score):
                name = str(item.get("name") or "")
                if not self._is_visible(name, whitelist, blacklist):
                    continue
                hits.append({**item, "category": category})
        hits.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return {"results": hits[:limit]}

    def skill_read(self, identity_id: str, name: str, *, category: str = "") -> dict[str, Any]:
        wanted_name = str(name or "").strip()
        if not wanted_name:
            return {"results": []}
        listing = self.skill_list(identity_id)["results"]
        categories = (category,) if category else ("shortlist", "builtin", "user")
        for current_category in categories:
            for item in listing:
                if item["category"] != current_category:
                    continue
                if str(item["name"] or "") != wanted_name:
                    continue
                prompt_text = self.skillset.render_prompt([str(item["path"])])
                return {
                    "results": [
                        {
                            "category": current_category,
                            "name": item["name"],
                            "path": item["path"],
                            "prompt_text": prompt_text,
                        }
                    ]
                }
        return {"results": []}

    def _find_hub(self, hub_id: str) -> TrustedSkillHub:
        wanted = _validate_token(hub_id, "hub_id")
        for hub in self.trusted_hubs:
            if hub.hub_id == wanted:
                return hub
        raise FileNotFoundError(f"unknown trusted skill site: {wanted}")

    def _fetch_json(self, url: str) -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("hub index must be a JSON object")
        return data

    def _resolve_hub_entry(self, hub: TrustedSkillHub, skill_name: str) -> dict[str, Any]:
        data = self._fetch_json(hub.index_url)
        raw_skills = data.get("skills", {})
        if isinstance(raw_skills, dict):
            entries = []
            for key, value in raw_skills.items():
                if not isinstance(value, dict):
                    continue
                entry = dict(value)
                entry.setdefault("name", key)
                entries.append(entry)
        elif isinstance(raw_skills, list):
            entries = [dict(item) for item in raw_skills if isinstance(item, dict)]
        else:
            entries = []
        for entry in entries:
            if str(entry.get("name") or "") != skill_name:
                continue
            archive_url = str(
                entry.get("archive_url")
                or entry.get("download_url")
                or entry.get("zip_url")
                or ""
            ).strip()
            if not archive_url:
                raise ValueError(f"trusted skill entry missing archive url: {skill_name}")
            return {
                "name": str(entry.get("name") or skill_name),
                "version": str(entry.get("version") or ""),
                "summary": str(entry.get("summary") or entry.get("description") or ""),
                "archive_url": archive_url,
            }
        raise FileNotFoundError(f"skill not found in trusted site: {skill_name}")

    def _find_skill_root(self, extracted_root: str) -> str:
        matches: list[str] = []
        for current_root, _dirnames, filenames in os.walk(extracted_root):
            if "SKILL.md" in filenames:
                matches.append(os.path.realpath(current_root))
        if len(matches) != 1:
            raise ValueError("downloaded skill bundle must contain exactly one skill root")
        return matches[0]

    def install_skill(
        self,
        identity_id: str,
        hub_id: str,
        skill_name: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        self._skill_policy(identity_id)
        hub = self._find_hub(hub_id)
        entry = self._resolve_hub_entry(hub, skill_name)
        with urllib.request.urlopen(entry["archive_url"], timeout=30) as response:
            archive_bytes = response.read()
        with tempfile.TemporaryDirectory() as tmp:
            extract_root = os.path.join(tmp, "extract")
            os.makedirs(extract_root, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                archive.extractall(extract_root)
            skill_root = self._find_skill_root(extract_root)
            destination = os.path.join(self.user_root, _validate_token(entry["name"], "skill_name"))
            if os.path.exists(destination):
                if not force:
                    raise FileExistsError(f"skill already installed: {entry['name']}")
                shutil.rmtree(destination)
            os.makedirs(self.user_root, exist_ok=True)
            shutil.copytree(skill_root, destination)
            install_meta = {
                "hub_id": hub.hub_id,
                "index_url": hub.index_url,
                "archive_url": entry["archive_url"],
                "version": entry["version"],
            }
            with open(os.path.join(destination, ".INSTALL.json"), "w", encoding="utf-8") as handle:
                json.dump(install_meta, handle, indent=2, ensure_ascii=False)
        return {
            "name": entry["name"],
            "category": "user",
            "path": os.path.realpath(destination),
            "summary": entry["summary"],
            "hub_id": hub.hub_id,
            "version": entry["version"],
        }
