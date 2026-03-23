"""SkillSet wrapper around Hydrai ContexTree."""

from __future__ import annotations

import os
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

from hydrai_memory.contexttree import ContexTree, Embedder

try:
    import yaml
except ImportError:  # pragma: no cover - exercised when PyYAML is absent
    yaml = None


class SkillSet:
    """OpenClaw-compatible skill discovery and prompt rendering."""

    def __init__(
        self,
        *,
        config_path: str | None = None,
        llm_url: str | None = None,
        llm_model: str = "",
        vl_url: str | None = None,
        vl_model: str = "",
        embedder: Embedder | None = None,
        text_max_bytes: int = 65536,
        image_max_bytes: int = 1024 * 1024,
        video_max_bytes: int = 10 * 1024 * 1024,
    ):
        self.config_path = os.path.realpath(config_path) if config_path else None
        self.llm_url = llm_url
        self.llm_model = llm_model
        self.vl_url = vl_url
        self.vl_model = vl_model
        self.embedder = embedder
        self.text_max_bytes = int(text_max_bytes)
        self.image_max_bytes = int(image_max_bytes)
        self.video_max_bytes = int(video_max_bytes)

    def list_skills(self, root: str, depth: int = 2, summary_depth: int = 2) -> list[dict[str, str]]:
        try:
            tree = self._make_tree(root)
            entries = tree.view(depth=depth, summary_depth=summary_depth)
            results: list[dict[str, str]] = []
            seen: set[str] = set()
            for entry in entries:
                rel_path = entry.get("path", "")
                if not isinstance(rel_path, str) or not rel_path.endswith("/SKILL.md"):
                    continue
                skill_rel = rel_path[: -len("/SKILL.md")]
                if not skill_rel or skill_rel in seen:
                    continue
                seen.add(skill_rel)
                skill_path = os.path.join(tree.root, skill_rel)
                meta = self._read_skill_meta(skill_path)
                results.append(
                    {
                        "name": meta["name"] or os.path.basename(skill_path),
                        "path": skill_path,
                        "summary": entry.get("summary", "") or meta["description"],
                    }
                )
            results.sort(key=lambda item: item["name"])
            return results
        except Exception:
            return self._scan_skill_dirs(root)

    def search_skills(
        self, root: str, query: str, limit: int = 10, min_score: float = 0.3
    ) -> list[dict[str, Any]]:
        text = str(query or "").strip()
        if not text:
            return []
        try:
            tree = self._make_tree(root)
            results = tree.search_by_text(text, top_k=max(limit * 4, limit), min_score=min_score)
            deduped: dict[str, dict[str, Any]] = {}
            for hit in results.get("results", []):
                matched_rel = hit.get("path", "")
                if not isinstance(matched_rel, str):
                    continue
                skill_path = self._resolve_skill_root(tree.root, matched_rel)
                if not skill_path:
                    continue
                meta = self._read_skill_meta(skill_path)
                score = float(hit.get("score", 0.0))
                current = deduped.get(skill_path)
                if current is not None and score <= current["score"]:
                    continue
                deduped[skill_path] = {
                    "name": meta["name"] or os.path.basename(skill_path),
                    "path": skill_path,
                    "summary": meta["description"] or hit.get("summary", ""),
                    "score": score,
                    "matched_path": self._matched_abs_path(tree.root, matched_rel, skill_path),
                }
            ordered = sorted(deduped.values(), key=lambda item: item["score"], reverse=True)
            if ordered:
                return ordered[:limit]
        except Exception:
            pass
        return self._search_skill_dirs(root, query=text, limit=limit)

    def render_prompt(self, skill_paths: list[str]) -> str:
        blocks: list[str] = []
        for skill_path in skill_paths:
            skill_root = os.path.realpath(skill_path)
            meta = self._read_skill_meta(skill_root)
            name = meta["name"] or os.path.basename(skill_root)
            description = meta["description"]
            lines = [f'<skill name="{name}" path="{skill_root}">']
            if description:
                lines.append(f"Description: {description}")
                lines.append("")
            body = meta["body"].strip()
            if body:
                lines.append(body)
            lines.append("</skill>")
            blocks.append("\n".join(lines).strip())
        return "\n\n".join(blocks)

    def deploy_defaults(
        self,
        root: str,
        *,
        categories: tuple[str, ...] = ("shortlist", "builtin"),
    ) -> dict[str, Any]:
        target_root = Path(root).expanduser().resolve()
        target_root.mkdir(parents=True, exist_ok=True)
        created: list[str] = []
        skipped: list[str] = []
        shipped_root = resources.files("hydrai_memory.skillset").joinpath("skills")
        for category in categories:
            if category not in {"shortlist", "builtin"}:
                raise ValueError(f"unknown default skill category: {category}")
            destination = target_root / category
            if destination.exists():
                skipped.append(category)
                continue
            self._copy_traversable_tree(shipped_root.joinpath(category), destination)
            created.append(category)
        return {"root": str(target_root), "created": created, "skipped": skipped}

    def initialize(
        self,
        root: str,
        *,
        categories: tuple[str, ...] = ("shortlist", "builtin"),
    ) -> dict[str, Any]:
        return self.deploy_defaults(root, categories=categories)

    def render_default_prompt(self, category: str, skill_names: list[str] | None = None) -> str:
        with resources.as_file(resources.files("hydrai_memory.skillset").joinpath("skills", category)) as root:
            selected_paths: list[str] = []
            wanted = set(skill_names) if skill_names is not None else None
            for entry in sorted(Path(root).iterdir(), key=lambda item: item.name):
                if not entry.is_dir() or not (entry / "SKILL.md").is_file():
                    continue
                if wanted is not None and entry.name not in wanted:
                    meta = self._read_skill_meta(str(entry))
                    if meta["name"] not in wanted:
                        continue
                selected_paths.append(str(entry))
            return self.render_prompt(selected_paths)

    def list_default_skills(self, category: str, depth: int = 2, summary_depth: int = 2) -> list[dict[str, str]]:
        with resources.as_file(resources.files("hydrai_memory.skillset").joinpath("skills", category)) as root:
            return self.list_skills(str(root), depth=depth, summary_depth=summary_depth)

    def search_default_skills(
        self, category: str, query: str, limit: int = 10, min_score: float = 0.3
    ) -> list[dict[str, Any]]:
        with resources.as_file(resources.files("hydrai_memory.skillset").joinpath("skills", category)) as root:
            return self.search_skills(str(root), query=query, limit=limit, min_score=min_score)

    def _make_tree(self, root: str) -> ContexTree:
        return ContexTree(
            root,
            config_path=self.config_path,
            llm_url=self.llm_url,
            llm_model=self.llm_model,
            vl_url=self.vl_url,
            vl_model=self.vl_model,
            embedder=self.embedder,
            text_max_bytes=self.text_max_bytes,
            image_max_bytes=self.image_max_bytes,
            video_max_bytes=self.video_max_bytes,
        )

    def _resolve_skill_root(self, root: str, matched_rel: str) -> str:
        rel = matched_rel.rstrip("/")
        if rel in {"", "/"}:
            return ""
        parts = [part for part in rel.split("/") if part]
        while parts:
            candidate = os.path.join(root, *parts)
            if os.path.isfile(os.path.join(candidate, "SKILL.md")):
                return os.path.realpath(candidate)
            parts.pop()
        return ""

    def _matched_abs_path(self, root: str, matched_rel: str, skill_path: str) -> str:
        rel = matched_rel.rstrip("/")
        if rel in {"", "/"}:
            return skill_path
        return os.path.realpath(os.path.join(root, rel))

    def _read_skill_meta(self, skill_path: str) -> dict[str, str]:
        skill_md = os.path.join(skill_path, "SKILL.md")
        if not os.path.isfile(skill_md):
            raise FileNotFoundError(f"Missing SKILL.md in {skill_path}")
        with open(skill_md, "r", encoding="utf-8") as handle:
            raw = handle.read()
        frontmatter, body = _split_frontmatter(raw)
        return {
            "name": _clean_frontmatter_value(frontmatter.get("name", "")),
            "description": _clean_frontmatter_value(frontmatter.get("description", "")),
            "body": body,
        }

    def _copy_traversable_tree(self, source: Any, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for entry in source.iterdir():
            target = destination / entry.name
            if entry.is_dir():
                self._copy_traversable_tree(entry, target)
                continue
            with resources.as_file(entry) as materialized:
                shutil.copy2(materialized, target)

    def _scan_skill_dirs(self, root: str) -> list[dict[str, str]]:
        root_path = Path(root).expanduser().resolve()
        results: list[dict[str, str]] = []
        if not root_path.is_dir():
            return results
        skill_roots: list[Path] = []
        for current_root, dirnames, filenames in os.walk(root_path):
            if "SKILL.md" not in filenames:
                continue
            current = Path(current_root)
            skill_roots.append(current)
            dirnames[:] = []
        for entry in sorted(skill_roots, key=lambda item: str(item.relative_to(root_path))):
            meta = self._read_skill_meta(str(entry))
            results.append(
                {
                    "name": meta["name"] or entry.name,
                    "path": str(entry.resolve()),
                    "summary": meta["description"],
                }
            )
        return results

    def _search_skill_dirs(self, root: str, *, query: str, limit: int) -> list[dict[str, Any]]:
        q = query.strip().lower()
        if not q:
            return []
        query_tokens = {token for token in q.replace("-", " ").split() if token}
        results: list[dict[str, Any]] = []
        for skill in self._scan_skill_dirs(root):
            skill_md = os.path.join(skill["path"], "SKILL.md")
            haystacks = [skill["name"], skill["summary"]]
            try:
                haystacks.append(Path(skill_md).read_text(encoding="utf-8"))
            except OSError:
                pass
            haystack = "\n".join(haystacks).lower()
            if q in haystack:
                score = 1.0
            else:
                matched = sum(1 for token in query_tokens if token in haystack)
                if not matched:
                    continue
                score = matched / max(len(query_tokens), 1)
            results.append({**skill, "score": float(score), "matched_path": skill_md})
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    marker = "\n---\n"
    end = raw.find(marker, 4)
    if end == -1:
        return {}, raw
    frontmatter_raw = raw[4:end]
    body = raw[end + len(marker) :]
    if yaml is None:
        return {}, body
    parsed = yaml.safe_load(frontmatter_raw) or {}
    if not isinstance(parsed, dict):
        return {}, body
    return parsed, body


def _clean_frontmatter_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""
