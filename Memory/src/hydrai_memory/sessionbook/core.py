"""SessionBook built on Hydrai ContexTree."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path

from hydrai_memory.contexttree.core import ContexTree
from hydrai_memory.contexttree.embedder import Embedder
from hydrai_memory.contexttree.llm import LLMClient, ProxyLLMClient
from hydrai_memory.contexttree.summary import load_summary, save_summary, set_file_summary

logger = logging.getLogger(__name__)

_CHAPTER_RE = re.compile(r"^\d{6}\.log$")
_ATTACHMENT_RE = re.compile(r"^\d{4}\.[A-Za-z0-9]+$")

_CHAPTER_PROMPT = (
    "Summarize this conversation segment. Capture key topics discussed, "
    "decisions made, and any action items or open questions."
)

_SESSION_PROMPT = (
    "Summarize this session's contents. Write 1-2 sentences describing "
    "the overall topics and current state of the conversation."
)


def _validate_mode(mode: str) -> str:
    if mode not in {"rw", "ro"}:
        raise ValueError(f"Invalid mode: {mode!r}. Expected 'rw' or 'ro'.")
    return mode


def _validate_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {field_name}: must be a non-empty string.")
    return value


def _safe_limit(value, default: int) -> int:
    if not isinstance(value, int):
        return default
    if value <= 0:
        return default
    return value


def _default_config() -> dict:
    return {
        "channel": "",
        "identities": {},
        "resources": {},
        "brain": {},
        "attachments": {"next_serial": 1},
        "limits": {},
    }


def _validate_attachment_tag(tag: str) -> str:
    if not isinstance(tag, str) or not _ATTACHMENT_RE.match(tag):
        raise ValueError(f"Invalid attachment tag: {tag!r}")
    return tag


class SessionBook:
    """Append-only chat session with chapter rotation and progressive context."""

    @classmethod
    def create(cls, root: str, config: dict | str | None = None, **kwargs) -> "SessionBook":
        root = os.path.realpath(root)
        os.makedirs(root, exist_ok=True)
        if config is not None:
            if isinstance(config, str):
                config = json.loads(config)
            path = os.path.join(root, "config.json")
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            os.rename(tmp_path, path)
        return cls(root, **kwargs)

    def __init__(
        self,
        root: str,
        config_path: str | None = None,
        llm_url: str | None = None,
        llm_model: str = "",
        vl_url: str | None = None,
        vl_model: str = "",
        embedder: Embedder | None = None,
        max_chapter_bytes: int = 32768,
        min_break_bytes: int = 1024,
        recent_budget: int = 32768,
        context_budget: int = 65536,
    ):
        self.root = os.path.realpath(root)
        os.makedirs(self.root, exist_ok=True)
        self.tree = ContexTree(
            self.root,
            config_path=config_path,
            llm_url=llm_url,
            llm_model=llm_model,
            embedder=embedder,
            vl_url=vl_url,
            vl_model=vl_model,
        )
        self.llm: LLMClient | ProxyLLMClient | None = self.tree.llm
        self.embedder = self.tree.embedder or embedder
        self._write_lock = threading.Lock()

        limits = self._load_config().get("limits", {})
        self.max_chapter_bytes = _safe_limit(limits.get("max_chapter_bytes"), max_chapter_bytes)
        self.min_break_bytes = _safe_limit(limits.get("min_break_bytes"), min_break_bytes)
        self.recent_budget = _safe_limit(limits.get("recent_budget"), recent_budget)
        self.context_budget = _safe_limit(limits.get("context_budget"), context_budget)

    def _list_chapters(self) -> list[str]:
        try:
            entries = os.listdir(self.root)
        except OSError:
            return []
        chapters = [e for e in entries if _CHAPTER_RE.match(e)]
        chapters.sort()
        return chapters

    def _active_chapter(self) -> str | None:
        chapters = self._list_chapters()
        if not chapters:
            return None
        highest = chapters[-1]
        data = load_summary(self.root)
        entry = data["files"].get(highest)
        if entry and entry.get("text"):
            return None
        return highest

    def _next_chapter_name(self) -> str:
        chapters = self._list_chapters()
        if not chapters:
            return "000000.log"
        last_num = int(chapters[-1].split(".")[0])
        return f"{last_num + 1:06d}.log"

    def _chapter_path(self, chapter: str) -> str:
        return os.path.join(self.root, chapter)

    def _chapter_size(self, chapter: str) -> int:
        try:
            return os.path.getsize(self._chapter_path(chapter))
        except OSError:
            return 0

    def _create_chapter(self, name: str) -> None:
        with open(self._chapter_path(name), "w", encoding="utf-8") as f:
            pass

    def _close_and_summarize(self, chapter: str) -> None:
        path = self._chapter_path(chapter)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return

        summary_text = ""
        if self.llm and content.strip():
            summary_text = self._summarize_text(content, _CHAPTER_PROMPT, max_tokens=512)

        vec = ""
        if self.embedder and summary_text:
            vec = self.embedder.embed(f"[{chapter}] {summary_text}")

        data = load_summary(self.root)
        data = set_file_summary(data, chapter, summary_text, vec)
        save_summary(self.root, data)
        self._update_folder_summary()

    def _update_folder_summary(self) -> None:
        if not self.llm:
            return
        data = load_summary(self.root)
        summaries = []
        for chapter in self._list_chapters():
            entry = data["files"].get(chapter)
            if entry and entry.get("text"):
                summaries.append(entry["text"])
        if not summaries:
            return
        combined = "\n---\n".join(summaries)
        folder_summary = self._summarize_text(combined, _SESSION_PROMPT, max_tokens=200)
        if folder_summary:
            data["summary"] = folder_summary
            if self.embedder:
                root_label = os.path.basename(self.root) or "(root)"
                data["vec"] = self.embedder.embed(f"[({root_label})] {folder_summary}")
            save_summary(self.root, data)

    def _summarize_text(self, content: str, prompt: str, max_tokens: int) -> str:
        if not self.llm:
            return ""
        if isinstance(self.llm, ProxyLLMClient):
            policy = self.tree._resolve_summary_policy(self.root)
            return self.llm.summarize(
                content,
                prompt,
                route_port=policy["ports"]["text"],
                max_tokens=max_tokens,
            )
        return self.llm.summarize(content, prompt, max_tokens=max_tokens)

    def _recover(self) -> None:
        chapters = self._list_chapters()
        if len(chapters) <= 1:
            return
        data = load_summary(self.root)
        recovered = False
        for chapter in chapters[:-1]:
            entry = data["files"].get(chapter)
            if not entry or not entry.get("text"):
                self._close_and_summarize(chapter)
                recovered = True
        if recovered:
            self._update_folder_summary()

    def append(self, text: str) -> None:
        with self._write_lock:
            active = self._active_chapter()
            if active is None:
                active = self._next_chapter_name()
                self._create_chapter(active)
            if self._chapter_size(active) >= self.max_chapter_bytes:
                self._recover()
                self._close_and_summarize(active)
                active = self._next_chapter_name()
                self._create_chapter(active)

            path = self._chapter_path(active)
            size = self._chapter_size(active)
            with open(path, "a", encoding="utf-8") as f:
                if size > 0:
                    f.write(f"---\n{text}\n")
                else:
                    f.write(f"{text}\n")

    def end_chapter(self) -> bool:
        with self._write_lock:
            active = self._active_chapter()
            if active is None:
                return False
            if self._chapter_size(active) < self.min_break_bytes:
                return False
            self._recover()
            self._close_and_summarize(active)
            self._create_chapter(self._next_chapter_name())
            return True

    def _config_path(self) -> str:
        return os.path.join(self.root, "config.json")

    def _load_config(self) -> dict:
        path = self._config_path()
        if not os.path.isfile(path):
            return _default_config()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _default_config()
            defaults = _default_config()
            for key, value in defaults.items():
                data.setdefault(key, value)
            if not isinstance(data.get("attachments"), dict):
                data["attachments"] = {"next_serial": 1}
            data["attachments"]["next_serial"] = _safe_limit(data["attachments"].get("next_serial"), 1)
            if not isinstance(data.get("identities"), dict):
                data["identities"] = {}
            if not isinstance(data.get("resources"), dict):
                data["resources"] = {}
            if not isinstance(data.get("brain"), dict):
                data["brain"] = {}
            if not isinstance(data.get("limits"), dict):
                data["limits"] = {}
            return data
        except Exception:
            return _default_config()

    def _save_config(self, data: dict) -> None:
        path = self._config_path()
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.rename(tmp_path, path)

    def config(self) -> dict:
        return self._load_config()

    def _attachments_dir(self) -> str:
        return os.path.join(self.root, "attachments")

    def _attachment_relpath(self, tag: str) -> str:
        return f"attachments/{_validate_attachment_tag(tag)}"

    def _attachment_abspath(self, tag: str) -> str:
        return os.path.join(self._attachments_dir(), _validate_attachment_tag(tag))

    def _next_attachment_tag(self, cfg: dict, source_path: str) -> str:
        ext = Path(source_path).suffix.lower()
        if not ext:
            raise ValueError(f"Attachment must keep an extension: {source_path}")
        serial = _safe_limit(cfg["attachments"].get("next_serial"), 1)
        tag = f"{serial:04d}{ext}"
        cfg["attachments"]["next_serial"] = serial + 1
        return tag

    def attach(self, source_path: str, sender: str, summary: str = "") -> str:
        _validate_id(sender, "sender")
        if not os.path.isfile(source_path):
            raise FileNotFoundError(f"Source file not found: {source_path}")

        with self._write_lock:
            active = self._active_chapter()
            if active is None:
                active = self._next_chapter_name()
                self._create_chapter(active)
            elif self._chapter_size(active) >= self.max_chapter_bytes:
                self._recover()
                self._close_and_summarize(active)
                active = self._next_chapter_name()
                self._create_chapter(active)

            cfg = self._load_config()
            tag = self._next_attachment_tag(cfg, source_path)
            os.makedirs(self._attachments_dir(), exist_ok=True)
            self.tree.copy(self._attachment_relpath(tag), source_path, summary=summary)
            self._save_config(cfg)

            marker = f"[{sender} uploaded: {tag}]"
            path = self._chapter_path(active)
            size = self._chapter_size(active)
            with open(path, "a", encoding="utf-8") as f:
                if size > 0:
                    f.write(f"---\n{marker}\n")
                else:
                    f.write(f"{marker}\n")

            return tag

    def attachment_info(self, tags: list[str]) -> list[dict]:
        result: list[dict] = []
        summary_data = load_summary(self._attachments_dir()) if os.path.isdir(self._attachments_dir()) else {"files": {}}
        for tag in tags:
            _validate_attachment_tag(tag)
            path = self._attachment_abspath(tag)
            if not os.path.isfile(path):
                continue
            entry = summary_data.get("files", {}).get(tag, {})
            summary = entry.get("text", "") if isinstance(entry, dict) else ""
            result.append({"tag": tag, "path": path, "summary": summary})
        return result

    def latest_attachments(self, limit: int = 10) -> list[dict]:
        limit = _safe_limit(limit, 10)
        try:
            names = [name for name in os.listdir(self._attachments_dir()) if _ATTACHMENT_RE.match(name)]
        except OSError:
            return []
        names.sort(reverse=True)
        return self.attachment_info(names[:limit])

    def invite(self, identity_id: str, mode: str = "rw") -> None:
        _validate_id(identity_id, "identity_id")
        _validate_mode(mode)
        with self._write_lock:
            cfg = self._load_config()
            cfg["identities"][identity_id] = mode
            self._save_config(cfg)

    def kick(self, identity_id: str) -> None:
        _validate_id(identity_id, "identity_id")
        with self._write_lock:
            cfg = self._load_config()
            cfg["identities"].pop(identity_id, None)
            self._save_config(cfg)

    def mount(self, resource_id: str, mode: str = "rw") -> None:
        _validate_id(resource_id, "resource_id")
        _validate_mode(mode)
        with self._write_lock:
            cfg = self._load_config()
            cfg["resources"][resource_id] = mode
            self._save_config(cfg)

    def unmount(self, resource_id: str) -> None:
        _validate_id(resource_id, "resource_id")
        with self._write_lock:
            cfg = self._load_config()
            cfg["resources"].pop(resource_id, None)
            self._save_config(cfg)

    def query(self, query_embed: str | None = None, top_k: int = 10) -> dict:
        cfg = self._load_config()
        identities = cfg.get("identities", {})
        resources = cfg.get("resources", {})

        chapters = self._list_chapters()
        if not chapters:
            result: dict = {
                "context": "",
                "summary": "",
                "identities": identities,
                "resources": resources,
            }
            if query_embed is not None:
                result["results"] = []
            return result

        data = load_summary(self.root)
        chapter_info = []
        for ch in chapters:
            size = self._chapter_size(ch)
            entry = data["files"].get(ch)
            summary_text = entry["text"] if entry and entry.get("text") else ""
            chapter_info.append({"name": ch, "size": size, "summary": summary_text, "closed": bool(summary_text)})

        recent_start = len(chapter_info)
        cumulative_raw = 0
        for i in range(len(chapter_info) - 1, -1, -1):
            cumulative_raw += chapter_info[i]["size"]
            recent_start = i
            if cumulative_raw >= self.recent_budget:
                break

        prior_start = recent_start
        cumulative_prior = 0
        for i in range(recent_start - 1, -1, -1):
            s = chapter_info[i]["summary"]
            cumulative_prior += len(s.encode("utf-8")) if s else 0
            prior_start = i
            if cumulative_raw + cumulative_prior >= self.context_budget:
                break

        parts = []
        for i in range(prior_start, recent_start):
            s = chapter_info[i]["summary"]
            if s:
                parts.append(s)
        for i in range(recent_start, len(chapter_info)):
            path = self._chapter_path(chapter_info[i]["name"])
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if content.strip():
                    parts.append(content.rstrip("\n"))
            except OSError:
                pass

        result = {
            "context": "\n---\n".join(parts),
            "summary": data.get("summary", ""),
            "identities": identities,
            "resources": resources,
        }
        if query_embed is not None:
            result["results"] = self.tree.search_by_embedding(query_embed, top_k=top_k).get("results", [])
        return result

    def chapter_info(self, chapter: str) -> dict | None:
        if not _CHAPTER_RE.match(chapter):
            return None
        path = self._chapter_path(chapter)
        if not os.path.isfile(path):
            return None
        try:
            stat = os.stat(path)
        except OSError:
            return None
        created = getattr(stat, "st_birthtime", stat.st_ctime)
        data = load_summary(self.root)
        entry = data["files"].get(chapter)
        closed = bool(entry and entry.get("text"))
        return {
            "chapter": chapter,
            "created": created,
            "modified": stat.st_mtime,
            "size": stat.st_size,
            "closed": closed,
        }

    def view(self, **kwargs) -> list[dict]:
        return self.tree.view(**kwargs)

    def read(self, paths: list[str]) -> dict[str, str | dict]:
        return self.tree.read(paths)

    def search_by_text(self, query: str, **kwargs) -> dict:
        return self.tree.search_by_text(query, **kwargs)
