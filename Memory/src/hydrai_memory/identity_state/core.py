"""IdentityState built on Hydrai ContexTree."""

from __future__ import annotations

import json
import os
import re
import unicodedata

from hydrai_memory.contexttree.core import ContexTree
from hydrai_memory.contexttree.embedder import Embedder

_SERIAL_RE = re.compile(r"^(\d{4})\.")


def _validate_token(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {field_name}: must be a non-empty string.")
    if "/" in value or "\\" in value:
        raise ValueError(f"Invalid {field_name}: path separators are not allowed.")
    return value.strip()


def _validate_config_dict(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    return data


def _slugify_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", str(title or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    chars = []
    last_dash = False
    for ch in text:
        if ch.isalnum():
            chars.append(ch)
            last_dash = False
            continue
        if not last_dash:
            chars.append("-")
            last_dash = True
    slug = "".join(chars).strip("-")
    return slug or "note"


class IdentityState(ContexTree):
    """Manage an identity's self model and continuity state."""

    DIRS = ("identity", "dynamics", "ongoing", "memorables", "impulses")

    @classmethod
    def create(
        cls,
        root: str,
        config: dict | str | None = None,
        **kwargs,
    ) -> "IdentityState":
        root = os.path.realpath(root)
        os.makedirs(root, exist_ok=True)
        for d in cls.DIRS:
            os.makedirs(os.path.join(root, d), exist_ok=True)
        for name in ("SOUL.md", "PERSONA.md"):
            path = os.path.join(root, "identity", name)
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    pass
        if config is not None:
            if isinstance(config, str):
                config = json.loads(config)
            _validate_config_dict(config)
            path = os.path.join(root, "config.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            os.rename(tmp, path)
        return cls(root, **kwargs)

    def __init__(self, root: str, embedder: Embedder | None = None, **kwargs):
        super().__init__(root, embedder=embedder, **kwargs)

    def soul(self) -> str:
        result = self.read(["identity/SOUL.md"])
        val = result.get("identity/SOUL.md", "")
        return val if isinstance(val, str) else ""

    def set_soul(self, content: str) -> None:
        self.write_text("identity/SOUL.md", content)

    def persona(self) -> str:
        result = self.read(["identity/PERSONA.md"])
        val = result.get("identity/PERSONA.md", "")
        return val if isinstance(val, str) else ""

    def set_persona(self, content: str) -> None:
        self.write_text("identity/PERSONA.md", content)

    def config(self) -> dict:
        path = os.path.join(self.root, "config.json")
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def set_config(self, data: dict) -> None:
        _validate_config_dict(data)
        path = os.path.join(self.root, "config.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.rename(tmp, path)

    def dynamic(self, name: str) -> str:
        name = _validate_token(name, "name")
        result = self.read([f"dynamics/{name}.md"])
        val = result.get(f"dynamics/{name}.md", "")
        return val if isinstance(val, str) else ""

    def set_dynamic(self, name: str, content: str) -> None:
        name = _validate_token(name, "name")
        self.write_text(f"dynamics/{name}.md", content)

    def ongoing(self, session_id: str) -> str:
        session_id = _validate_token(session_id, "session_id")
        result = self.read([f"ongoing/{session_id}.md"])
        val = result.get(f"ongoing/{session_id}.md", "")
        return val if isinstance(val, str) else ""

    def set_ongoing(self, session_id: str, content: str) -> None:
        session_id = _validate_token(session_id, "session_id")
        self.write_text(f"ongoing/{session_id}.md", content)

    def _next_serial(self) -> int:
        memorables_dir = os.path.join(self.root, "memorables")
        if not os.path.isdir(memorables_dir):
            return 1
        highest = 0
        for entry in os.listdir(memorables_dir):
            m = _SERIAL_RE.match(entry)
            if m:
                highest = max(highest, int(m.group(1)))
        return highest + 1

    def memorable(self, name: str) -> str:
        name = _validate_token(name, "name")
        result = self.read([f"memorables/{name}"])
        val = result.get(f"memorables/{name}", "")
        return val if isinstance(val, str) else ""

    def add_memorable(self, title: str, content: str) -> str:
        _validate_token(title, "title")
        serial = self._next_serial()
        filename = f"{serial:04d}.{_slugify_title(title)}.md"
        self.write_text(f"memorables/{filename}", content)
        return filename

    def get_sessions(self) -> list[str]:
        ongoing_dir = os.path.join(self.root, "ongoing")
        if not os.path.isdir(ongoing_dir):
            return []
        return sorted(
            f.removesuffix(".md")
            for f in os.listdir(ongoing_dir)
            if f.endswith(".md") and not f.startswith(".")
        )

    def get_friends(self) -> list[str]:
        dynamics_dir = os.path.join(self.root, "dynamics")
        if not os.path.isdir(dynamics_dir):
            return []
        return sorted(
            f.removesuffix(".md")
            for f in os.listdir(dynamics_dir)
            if f.endswith(".md") and not f.startswith(".") and f != "self.md"
        )

    def query(
        self,
        *,
        session_id: str | None = None,
        query_embed: str | None = None,
        query_text: str | None = None,
        top_k: int = 10,
    ) -> dict:
        if query_embed is None and query_text is None:
            raise ValueError("IdentityState.query requires query_embed or query_text")
        exclude = {"config.json"}
        view = [item for item in self.view(depth=2, summary_depth=1) if item["path"] not in exclude]
        result: dict = {
            "soul": self.soul(),
            "persona": self.persona(),
            "view": view,
        }
        if session_id:
            ongoing_content = self.ongoing(session_id)
            if ongoing_content:
                result["ongoing"] = ongoing_content
        search_paths = ["memorables", "dynamics", "ongoing"]
        if query_embed is not None:
            out = self.search_by_embedding(query_embed, top_k=top_k, paths=search_paths)
            result["results"] = out.get("results", [])
        else:
            out = self.search_by_text(str(query_text or ""), top_k=top_k, paths=search_paths)
            result["results"] = out.get("results", [])
        return result

    def evolve(
        self,
        *,
        new_memorables: list[dict] | None = None,
        update_dynamics: list[dict] | None = None,
        update_ongoing: list[dict] | None = None,
    ) -> dict:
        mem_count = 0
        dyn_count = 0
        ong_count = 0

        if new_memorables:
            for i, item in enumerate(new_memorables):
                if not isinstance(item, dict) or "title" not in item or "content" not in item:
                    raise ValueError(f"new_memorables[{i}] must contain 'title' and 'content'")
                self.add_memorable(item["title"], item["content"])
                mem_count += 1

        if update_dynamics:
            for i, item in enumerate(update_dynamics):
                if not isinstance(item, dict) or "name" not in item or "content" not in item:
                    raise ValueError(f"update_dynamics[{i}] must contain 'name' and 'content'")
                self.set_dynamic(item["name"], item["content"])
                dyn_count += 1

        if update_ongoing:
            for i, item in enumerate(update_ongoing):
                if not isinstance(item, dict) or "session_id" not in item or "content" not in item:
                    raise ValueError(f"update_ongoing[{i}] must contain 'session_id' and 'content'")
                self.set_ongoing(item["session_id"], item["content"])
                ong_count += 1

        self.sync()

        return {
            "ok": True,
            "memorables_added": mem_count,
            "dynamics_updated": dyn_count,
            "ongoing_updated": ong_count,
        }
