"""ContexTree class implementation (v2)."""

from __future__ import annotations

import logging
import os
import shutil
import threading

from .detect import detect_encoding, get_mime_type, is_image_file, is_text_file, is_video_file
from .embedder import Embedder, build_proxy_embedder
from .llm import LLMClient, ProxyLLMClient, ProxyVLClient, VLClient
from .prompt_config import SummaryBackendConfig, load_summary_config, resolve_local_prompt_overrides
from .search import search_vectors
from .summary import (
    SUMMARY_FILENAME,
    get_file_summary,
    get_summary_mtime,
    load_summary,
    merge_entries,
    prune_entries,
    remove_file_entry,
    rename_file_entry,
    save_summary,
    set_file_summary,
)
from .validate import validate_path

logger = logging.getLogger(__name__)


class ContexTree:
    def __init__(
        self,
        root: str,
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
        self.root = os.path.realpath(root)
        if not os.path.isdir(self.root):
            raise NotADirectoryError(f"Not a directory: {self.root}")
        self.config_path = os.path.realpath(config_path) if config_path else ""
        self.summary_config: SummaryBackendConfig | None = (
            load_summary_config(self.config_path) if self.config_path else None
        )
        if self.summary_config is not None:
            self.text_max_bytes = self.summary_config.text_max_bytes
            self.image_max_bytes = self.summary_config.image_max_bytes
            self.video_max_bytes = self.summary_config.video_max_bytes
        else:
            self.text_max_bytes = text_max_bytes
            self.image_max_bytes = image_max_bytes
            self.video_max_bytes = video_max_bytes
        self.llm: LLMClient | ProxyLLMClient | None
        self.vl: VLClient | ProxyVLClient | None
        if self.summary_config is not None:
            self.llm = ProxyLLMClient(self.summary_config.intelligence_base_url)
            self.vl = ProxyVLClient(self.summary_config.intelligence_base_url)
        else:
            self.llm = LLMClient(llm_url, llm_model) if llm_url else None
            self.vl = VLClient(vl_url, vl_model) if vl_url else None
        self.embedder: Embedder | None = embedder or (
            build_proxy_embedder(self.config_path) if self.summary_config is not None else None
        )
        self._write_lock = threading.Lock()
        self._write_pending = False
        self._sync_lock = threading.Lock()
        self._preempt = False
        # Maintenance loop state
        self._maint_thread: threading.Thread | None = None
        self._maint_stop = threading.Event()
        self._maint_interval: float = 0

    # ------------------------------------------------------------------
    # Thinker Tools (read-only, no locks)
    # ------------------------------------------------------------------

    def search_by_text(
        self, query: str, top_k: int = 10, min_score: float = 0.3,
        paths: list[str] | None = None,
    ) -> dict:
        """Embed query text, then search all summary vectors."""
        empty = {"results": [], "checked": 0, "missing": 0}
        if not self.embedder:
            return empty
        vec = self.embedder.embed(query)
        if not vec:
            return empty
        query_arr = self.embedder.decode(vec)
        return search_vectors(self.root, query_arr, self.embedder, top_k, min_score, paths=paths)

    def view(
        self, path: str = "", depth: int = -1, summary_depth: int = -1
    ) -> list[dict]:
        """Return a structured view of the directory tree starting from path."""
        if summary_depth == -1:
            summary_depth = depth
        # Resolve the starting directory
        if path:
            start_abs = validate_path(self.root, path)
        else:
            start_abs = self.root
        if not os.path.isdir(start_abs):
            raise NotADirectoryError(f"Not a directory: {path}")
        return self._view_folder(start_abs, depth=depth, summary_depth=summary_depth)

    def read(self, paths: list[str]) -> dict[str, str | dict]:
        """Read file contents. Returns dict keyed by relative path."""
        result: dict[str, str | dict] = {}
        for rel_path in paths:
            # Validate path
            try:
                abs_path = validate_path(self.root, rel_path)
            except ValueError:
                result[rel_path] = {"error": "Invalid path."}
                continue
            if not os.path.isfile(abs_path):
                result[rel_path] = {"error": "File not found."}
                continue
            if is_text_file(abs_path):
                encoding = detect_encoding(abs_path) or "utf-8"
                try:
                    file_size = os.path.getsize(abs_path)
                    with open(abs_path, "r", encoding=encoding, errors="replace") as f:
                        content = f.read(self.text_max_bytes)
                    if file_size > self.text_max_bytes:
                        remaining = file_size - self.text_max_bytes
                        content += f"\n... {remaining:,} more bytes"
                    result[rel_path] = content
                except OSError:
                    result[rel_path] = {"error": "File not found."}
            else:
                # Binary file — return summary
                dir_path = os.path.dirname(abs_path)
                filename = os.path.basename(abs_path)
                data = load_summary(dir_path)
                s = get_file_summary(data, filename)
                result[rel_path] = {"summary": s}
        return result

    # ------------------------------------------------------------------
    # Writer Tools (acquire write lock)
    # ------------------------------------------------------------------

    def write_text(self, path: str, content: str, summary: str = "") -> None:
        """Write (create or overwrite) a text file."""
        abs_path = validate_path(self.root, path)
        dir_path = os.path.dirname(abs_path)
        self._write_pending = True
        with self._write_lock:
            self._write_pending = False
            os.makedirs(dir_path, exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            filename = os.path.basename(abs_path)
            data = load_summary(dir_path)
            rel = self._rel_prefix(dir_path) + filename
            vec = self._embed_file(rel, summary)
            data = set_file_summary(data, filename, summary, vec)
            save_summary(dir_path, data)

    def append_text(self, path: str, content: str, summary: str = "") -> None:
        """Append text to an existing file."""
        abs_path = validate_path(self.root, path)
        self._write_pending = True
        with self._write_lock:
            self._write_pending = False
            if not os.path.isfile(abs_path):
                raise FileNotFoundError(f"File not found: {path}")
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                existing = f.read()
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(existing + "\n\n" + content)
            dir_path = os.path.dirname(abs_path)
            filename = os.path.basename(abs_path)
            data = load_summary(dir_path)
            rel = self._rel_prefix(dir_path) + filename
            vec = self._embed_file(rel, summary)
            data = set_file_summary(data, filename, summary, vec)
            save_summary(dir_path, data)

    def rename(self, path: str, new_name: str) -> None:
        """Rename a file within the same directory."""
        abs_path = validate_path(self.root, path)
        if "/" in new_name:
            raise ValueError("new_name must not contain '/'")
        self._write_pending = True
        with self._write_lock:
            self._write_pending = False
            if not os.path.isfile(abs_path):
                raise FileNotFoundError(f"File not found: {path}")
            dir_path = os.path.dirname(abs_path)
            new_path = os.path.join(dir_path, new_name)
            if os.path.exists(new_path):
                raise FileExistsError(f"Target already exists: {new_name}")
            os.rename(abs_path, new_path)
            old_name = os.path.basename(abs_path)
            data = load_summary(dir_path)
            data = rename_file_entry(data, old_name, new_name)
            save_summary(dir_path, data)

    def delete(self, path: str) -> None:
        """Delete a file from the managed tree."""
        abs_path = validate_path(self.root, path)
        self._write_pending = True
        with self._write_lock:
            self._write_pending = False
            if not os.path.isfile(abs_path):
                raise FileNotFoundError(f"File not found: {path}")
            os.remove(abs_path)
            dir_path = os.path.dirname(abs_path)
            filename = os.path.basename(abs_path)
            data = load_summary(dir_path)
            data = remove_file_entry(data, filename)
            save_summary(dir_path, data)

    # ------------------------------------------------------------------
    # Internal Methods (not exposed to LLM)
    # ------------------------------------------------------------------

    def sync(
        self,
        path: str = "",
        reset: bool = False,
        discover_only: bool = False,
        mode: str = "soft",
        _bg: bool = False,
    ) -> dict:
        """Synchronize .SUMMARY.json files.

        path="": sync the entire tree (default).
        path="folder/": sync only that subfolder subtree.
        path="folder/file.txt": sync only that single file.

        mode="mutex": hold write lock for full run.
        mode="soft": check _write_pending between folders, yield if set.

        _bg: internal flag — True when called from the maintenance loop.
             Background sync uses non-blocking acquire and yields on preempt.
             High-priority sync (default) preempts background sync first.
        """
        if _bg:
            # Background: non-blocking acquire — skip if sync lock is held
            if not self._sync_lock.acquire(blocking=False):
                return {"error": "Sync already in progress"}
        else:
            # High-priority: preempt background sync, then block until lock free
            self._preempt = True
            self._sync_lock.acquire()
            self._preempt = False

        try:
            return self._sync_inner(path, reset, discover_only, mode, _bg)
        finally:
            self._sync_lock.release()

    def _sync_inner(
        self,
        path: str,
        reset: bool,
        discover_only: bool,
        mode: str,
        _bg: bool,
    ) -> dict:
        """Core sync logic. Called with _sync_lock held."""
        synced_folders = 0
        total_folders = 0
        files_summarized = 0
        interrupted = False
        errors: list[str] = []

        # Determine scope
        only_files: set[str] | None = None  # None = all files in folder

        if path and path != "/":
            try:
                target_abs = validate_path(self.root, path)
            except ValueError as e:
                return {"error": str(e)}
            if os.path.isfile(target_abs):
                # Single file — sync only its parent folder, only that file
                start_dir = os.path.dirname(target_abs)
                only_files = {os.path.basename(target_abs)}
            elif os.path.isdir(target_abs):
                start_dir = target_abs
            else:
                return {"error": f"Path not found: {path}"}
        else:
            start_dir = self.root

        # Collect directories bottom-up (deepest first)
        all_dirs: list[str] = []
        if only_files is not None:
            # Single file mode — just the parent folder
            all_dirs = [start_dir]
        else:
            for dirpath, dirnames, _filenames in os.walk(start_dir):
                dirnames[:] = sorted(
                    d for d in dirnames
                    if not d.startswith(".") and not os.path.islink(os.path.join(dirpath, d))
                )
                all_dirs.append(dirpath)
            all_dirs.reverse()
        total_folders = len(all_dirs)

        if mode == "mutex":
            with self._write_lock:
                for dir_path in all_dirs:
                    if _bg and self._preempt:
                        interrupted = True
                        break
                    try:
                        count = self._sync_folder(
                            dir_path, reset, discover_only, only_files)
                        synced_folders += 1
                        files_summarized += count
                    except Exception as e:
                        rel = os.path.relpath(dir_path, self.root)
                        if rel == ".":
                            rel = ""
                        else:
                            rel += "/"
                        msg = f"{rel}: {e}"
                        logger.warning("Sync error: %s", msg)
                        errors.append(msg)
        else:
            # soft mode — acquire/release lock per folder
            for dir_path in all_dirs:
                if self._write_pending or (_bg and self._preempt):
                    interrupted = True
                    break
                with self._write_lock:
                    try:
                        count = self._sync_folder(
                            dir_path, reset, discover_only, only_files)
                        synced_folders += 1
                        files_summarized += count
                    except Exception as e:
                        rel = os.path.relpath(dir_path, self.root)
                        if rel == ".":
                            rel = ""
                        else:
                            rel += "/"
                        msg = f"{rel}: {e}"
                        logger.warning("Sync error: %s", msg)
                        errors.append(msg)

        return {
            "synced_folders": synced_folders,
            "total_folders": total_folders,
            "files_summarized": files_summarized,
            "interrupted": interrupted,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Maintenance loop
    # ------------------------------------------------------------------

    def start_maintenance(self, interval: float = 300) -> None:
        """Start a background daemon thread that periodically runs soft sync.

        interval: seconds between sync runs (default 300 = 5 minutes).
        Raises RuntimeError if already running.
        """
        if self._maint_thread is not None and self._maint_thread.is_alive():
            raise RuntimeError("Maintenance already running")
        self._maint_interval = interval
        self._maint_stop.clear()
        self._maint_thread = threading.Thread(
            target=self._maintenance_loop, daemon=True)
        self._maint_thread.start()

    def stop_maintenance(self, timeout: float = 10) -> None:
        """Signal the maintenance loop to stop and wait for it to finish."""
        self._maint_stop.set()
        if self._maint_thread is not None:
            self._maint_thread.join(timeout=timeout)
            if not self._maint_thread.is_alive():
                self._maint_thread = None

    def maintenance_status(self) -> dict:
        """Return current maintenance loop state."""
        running = (self._maint_thread is not None
                   and self._maint_thread.is_alive())
        return {
            "running": running,
            "interval": self._maint_interval if running else 0,
        }

    def folder_summary(self, path: str = "") -> str:
        """Return the stored summary for a folder, or an empty string."""
        abs_path = validate_path(self.root, path) if path else self.root
        if not os.path.isdir(abs_path):
            raise NotADirectoryError(f"Not a directory: {path or '(root)'}")
        data = load_summary(abs_path)
        summary = data.get("summary", "")
        return summary if isinstance(summary, str) else ""

    def _maintenance_loop(self) -> None:
        """Background loop: sync(mode='soft', _bg=True), sleep, repeat."""
        while not self._maint_stop.is_set():
            try:
                self.sync(mode="soft", _bg=True)
            except Exception:
                logger.exception("Maintenance sync error")
            # Wait for interval, but wake up immediately if stop is set
            self._maint_stop.wait(timeout=self._maint_interval)

    def embed(self, text: str) -> str:
        """Vectorize text via the shared embedder. Returns base64 string."""
        if not self.embedder:
            return ""
        return self.embedder.embed(text)

    def search_by_embedding(
        self, vec_b64: str, top_k: int = 10, min_score: float = 0.3,
        paths: list[str] | None = None,
    ) -> dict:
        """Search with a pre-computed vector (base64 string)."""
        if not self.embedder:
            return {"results": [], "checked": 0, "missing": 0}
        query_arr = self.embedder.decode(vec_b64)
        return search_vectors(self.root, query_arr, self.embedder, top_k, min_score, paths=paths)

    def set_folder_summary(self, rel_path: str, summary_text: str) -> None:
        """Manually set a folder's summary. Sets manual=True."""
        if rel_path:
            abs_path = validate_path(self.root, rel_path)
        else:
            abs_path = self.root
        if not os.path.isdir(abs_path):
            raise NotADirectoryError(f"Not a directory: {rel_path or '(root)'}")
        data = load_summary(abs_path)
        data["summary"] = summary_text
        data["manual"] = True
        label = self._rel_prefix(abs_path) or "(root)"
        data["vec"] = self._embed_folder(label, summary_text)
        save_summary(abs_path, data)

    def set_folder_auto(self, rel_path: str) -> None:
        """Switch a folder's summary back to auto mode."""
        if rel_path:
            abs_path = validate_path(self.root, rel_path)
        else:
            abs_path = self.root
        if not os.path.isdir(abs_path):
            raise NotADirectoryError(f"Not a directory: {rel_path or '(root)'}")
        data = load_summary(abs_path)
        data["manual"] = False
        save_summary(abs_path, data)

    def copy(self, path: str, source_path: str, summary: str = "") -> None:
        """Copy an external file into the managed tree."""
        if not os.path.isfile(source_path):
            raise FileNotFoundError(f"Source file not found: {source_path}")
        abs_path = validate_path(self.root, path)
        dir_path = os.path.dirname(abs_path)
        self._write_pending = True
        with self._write_lock:
            self._write_pending = False
            os.makedirs(dir_path, exist_ok=True)
            shutil.copy2(source_path, abs_path)
            filename = os.path.basename(abs_path)
            data = load_summary(dir_path)
            rel = self._rel_prefix(dir_path) + filename
            vec = self._embed_file(rel, summary)
            data = set_file_summary(data, filename, summary, vec)
            save_summary(dir_path, data)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _rel_prefix(self, abs_dir: str) -> str:
        """Return the relative path prefix for embedding context.

        Returns "" for root, "docs/" for <root>/docs, etc.
        """
        rel = os.path.relpath(abs_dir, self.root)
        if rel == ".":
            return ""
        return rel.replace(os.sep, "/") + "/"

    def _embed_file(self, path: str, summary: str) -> str:
        """Embed a file summary with path-aware prefix."""
        if not summary or not self.embedder:
            return ""
        return self.embedder.embed(f"[{path}] {summary}")

    def _embed_folder(self, rel_path: str, summary: str) -> str:
        """Embed a folder summary with path-aware prefix."""
        if not summary or not self.embedder:
            return ""
        label = rel_path or "(root)"
        return self.embedder.embed(f"[{label}] {summary}")

    def _scan_dir(self, dir_path: str) -> tuple[list[str], list[str]]:
        """Scan a directory for non-hidden, non-symlink files and subfolders.

        Returns (filenames, subfolder_names) as sorted lists.
        """
        filenames: list[str] = []
        subfolders: list[str] = []
        try:
            entries = os.listdir(dir_path)
        except OSError:
            return filenames, subfolders
        for name in entries:
            if name.startswith("."):
                continue
            full = os.path.join(dir_path, name)
            if os.path.islink(full):
                continue
            if os.path.isdir(full):
                subfolders.append(name)
            elif os.path.isfile(full):
                filenames.append(name)
        return sorted(filenames), sorted(subfolders)

    def _sync_folder(
        self, dir_path: str, reset: bool, discover_only: bool,
        only_files: set[str] | None = None,
    ) -> int:
        """Sync a single folder. Returns number of files summarized.

        only_files: if set, only summarize/vectorize these filenames.
        Discovery and pruning still run for all files.
        """
        files_summarized = 0
        any_child_updated = False

        # Relative prefix for embedding context (e.g. "docs/" or "" for root)
        rel_prefix = self._rel_prefix(dir_path)

        # Step 1: Load
        data = load_summary(dir_path)
        summary_mtime = get_summary_mtime(dir_path)

        # Step 2-3: Scan directory
        filenames, subfolders = self._scan_dir(dir_path)
        existing_files = set(filenames)

        # Step 2: Prune deleted files
        data = prune_entries(data, existing_files)

        # Step 3: Discover new files
        data = merge_entries(data, existing_files)

        updated_files: set[str] = set()

        if not discover_only:
            # Step 4: Summarize files
            for filename, entry in data["files"].items():
                if only_files is not None and filename not in only_files:
                    continue
                full_path = os.path.join(dir_path, filename)
                if not os.path.isfile(full_path):
                    continue
                needs_summary = (
                    entry["text"] == ""
                    or reset
                    or _file_newer(full_path, summary_mtime)
                )
                if not needs_summary:
                    continue

                new_summary = ""
                policy = self._resolve_summary_policy(dir_path)
                if is_text_file(full_path):
                    if self.llm:
                        new_summary = self._summarize_text_file(full_path, policy)
                elif is_image_file(full_path):
                    if self.vl and self._within_media_limit(full_path, "image"):
                        new_summary = self._summarize_media_file(full_path, "image", policy)
                elif is_video_file(full_path):
                    if self.vl and self._within_media_limit(full_path, "video"):
                        new_summary = self._summarize_media_file(full_path, "video", policy)
                # else: other binary — skip

                if new_summary:
                    entry["text"] = new_summary
                    updated_files.add(filename)
                    any_child_updated = True
                    files_summarized += 1

            # Step 5: Vectorize files (include path for semantic context)
            if self.embedder:
                for filename, entry in data["files"].items():
                    if only_files is not None and filename not in only_files:
                        continue
                    if not entry["text"]:
                        continue
                    if entry["vec"] == "" or filename in updated_files:
                        rel = rel_prefix + filename
                        entry["vec"] = self._embed_file(rel, entry["text"])

            # Step 6: Folder summary
            if not data["manual"]:
                needs_folder = (
                    data["summary"] == ""
                    or reset
                    or any_child_updated
                )
                if needs_folder and self.llm:
                    folder_view = self._render_folder_view(dir_path)
                    new_folder_summary = self._summarize_folder_view(folder_view, dir_path)
                    if new_folder_summary:
                        data["summary"] = new_folder_summary
                        label = rel_prefix or "(root)"
                        data["vec"] = self._embed_folder(label, data["summary"])

        # Step 7: Save
        save_summary(dir_path, data)
        return files_summarized

    def _summarize_text_file(self, full_path: str, policy: dict | None = None) -> str:
        """Read a text file up to text_max_bytes and summarize via LLM."""
        encoding = detect_encoding(full_path) or "utf-8"
        try:
            with open(full_path, "r", encoding=encoding, errors="replace") as f:
                content = f.read(self.text_max_bytes)
        except OSError as e:
            logger.warning("Cannot read file %s: %s", full_path, e)
            return ""
        if not self.llm:
            return ""
        if self.summary_config is not None:
            assert isinstance(self.llm, ProxyLLMClient)
            assert policy is not None
            return self.llm.summarize(
                content,
                policy["prompts"]["text_summary"],
                route_port=policy["ports"]["text"],
                max_tokens=512,
            )
        assert isinstance(self.llm, LLMClient)
        return self.llm.summarize_text(content)

    def _summarize_folder_view(self, folder_view: str, dir_path: str) -> str:
        if not self.llm:
            return ""
        if self.summary_config is not None:
            assert isinstance(self.llm, ProxyLLMClient)
            policy = self._resolve_summary_policy(dir_path)
            return self.llm.summarize(
                folder_view,
                policy["prompts"]["folder_summary"],
                route_port=policy["ports"]["text"],
                max_tokens=200,
            )
        assert isinstance(self.llm, LLMClient)
        return self.llm.summarize_folder(folder_view)

    def _summarize_media_file(self, full_path: str, modality: str, policy: dict) -> str:
        if self.summary_config is not None:
            assert isinstance(self.vl, ProxyVLClient)
            prompt_key = "image_summary" if modality == "image" else "video_summary"
            port_key = "image" if modality == "image" else "video"
            return self.vl.summarize_media(
                full_path,
                route_port=policy["ports"][port_key],
                prompt=policy["prompts"][prompt_key],
            )
        if modality != "image":
            return ""
        assert isinstance(self.vl, VLClient)
        mime = get_mime_type(full_path) or "image/jpeg"
        return self.vl.summarize_image(full_path, mime)

    def _resolve_summary_policy(self, dir_path: str) -> dict:
        if self.summary_config is None:
            return {"prompts": {}, "ports": {}}
        overrides = resolve_local_prompt_overrides(self.root, dir_path)
        prompts = dict(self.summary_config.prompts)
        prompts.update(overrides.get("prompts", {}))
        ports = {
            "text": self.summary_config.text_port,
            "image": self.summary_config.image_port,
            "video": self.summary_config.video_port,
            "embedder": self.summary_config.embedder_port,
        }
        ports.update(overrides.get("ports", {}))
        return {"prompts": prompts, "ports": ports}

    def _within_media_limit(self, full_path: str, modality: str) -> bool:
        try:
            file_size = os.path.getsize(full_path)
        except OSError:
            return False
        limit = self.image_max_bytes if modality == "image" else self.video_max_bytes
        if file_size <= limit:
            return True
        logger.info("Skipping %s summary for oversized file %s (%s > %s)", modality, full_path, file_size, limit)
        return False

    def _render_folder_view(self, dir_path: str) -> str:
        """Render a depth=1, summary_depth=1 view of a folder as plain text.

        Used as input for LLM folder summarization.
        """
        items = self._view_folder(dir_path, depth=1, summary_depth=1)
        lines: list[str] = []
        for item in items:
            p = item["path"]
            parts = []
            parts.append(p)
            if "size" in item:
                parts.append(_human_size(item["size"]))
            if "summary" in item:
                parts.append(item["summary"])
            lines.append("  ".join(parts))
        return "\n".join(lines)

    def _view_folder(
        self,
        dir_path: str,
        depth: int,
        summary_depth: int,
        _child_depth: int = 1,
    ) -> list[dict]:
        """Build the view list for a folder recursively.

        All paths are full relative paths from self.root.
        _child_depth tracks the depth of items inside this folder
        relative to the original view starting point (1 = direct children).
        """
        result: list[dict] = []

        # Relative prefix from root
        rel_prefix = self._rel_prefix(dir_path)

        # Load summary or discover from filesystem
        data = load_summary(dir_path)
        has_summary_file = os.path.isfile(os.path.join(dir_path, SUMMARY_FILENAME))

        if has_summary_file:
            file_names = sorted(data["files"].keys())
        else:
            file_names, _ = self._scan_dir(dir_path)

        # Discover subfolders from filesystem (never from summary)
        _, subfolder_names = self._scan_dir(dir_path)

        show_summary = _include_summary(_child_depth, summary_depth)

        # Interleave files and folders in sorted order
        # Folders get a trailing "/" so they sort among files naturally
        all_items: list[tuple[str, str]] = []  # (sort_key, type)
        for fn in file_names:
            all_items.append((fn, "file"))
        for sf in subfolder_names:
            all_items.append((sf + "/", "folder"))
        all_items.sort(key=lambda x: x[0])

        for sort_key, item_type in all_items:
            if item_type == "file":
                filename = sort_key
                full_path = os.path.join(dir_path, filename)
                entry: dict = {"path": rel_prefix + filename}
                try:
                    entry["size"] = os.path.getsize(full_path)
                except OSError:
                    entry["size"] = 0
                if show_summary:
                    s = get_file_summary(data, filename)
                    if s:
                        entry["summary"] = s
                result.append(entry)
            else:
                # folder
                folder_name = sort_key.rstrip("/")
                subfolder_path = os.path.join(dir_path, folder_name)
                if not os.path.isdir(subfolder_path):
                    continue
                folder_entry: dict = {"path": rel_prefix + folder_name + "/"}
                if show_summary:
                    sub_data = load_summary(subfolder_path)
                    if sub_data["summary"]:
                        folder_entry["summary"] = sub_data["summary"]
                result.append(folder_entry)

                # Recurse if depth allows
                next_depth = _child_depth + 1
                can_recurse = depth == -1 or next_depth <= depth
                if can_recurse:
                    children = self._view_folder(
                        subfolder_path,
                        depth=depth,
                        summary_depth=summary_depth,
                        _child_depth=next_depth,
                    )
                    result.extend(children)

        return result


def _include_summary(item_depth: int, summary_depth: int) -> bool:
    """Return True if summaries should be included at this depth."""
    if summary_depth == -1:
        return True
    return item_depth <= summary_depth


def _file_newer(file_path: str, reference_mtime: float) -> bool:
    """Return True if file's mtime is newer than reference_mtime."""
    try:
        return os.path.getmtime(file_path) > reference_mtime
    except OSError:
        return False


def _human_size(size_bytes: int) -> str:
    """Format byte size in human-readable form (e.g. 1.2K, 200.3K)."""
    if size_bytes < 1000:
        return str(size_bytes)
    for unit in ("K", "M", "G"):
        size_bytes /= 1000
        if size_bytes < 1000:
            if size_bytes == int(size_bytes):
                return f"{int(size_bytes)}{unit}"
            return f"{size_bytes:.1f}{unit}"
    return f"{size_bytes:.1f}T"
