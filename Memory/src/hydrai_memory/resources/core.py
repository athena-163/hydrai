"""Sandbox-local resource registry and maintenance management."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any

from hydrai_memory.contexttree import ContexTree, MaintenanceHandle, start_registered_maintenance

DEFAULT_MAINTAIN_INTERVAL_SEC = 300.0


def _validate_resource_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("resource id must be a non-empty string")
    if "/" in value or "\\" in value:
        raise ValueError("resource id must not contain path separators")
    return value.strip()


def _normalize_interval(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        if value < 0:
            return None
        return value
    return None


def _summary_for_root(root: str) -> str:
    path = os.path.join(root, ".SUMMARY.json")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    summary = data.get("summary", "")
    return summary if isinstance(summary, str) else ""


def _normalize_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


class ResourceRegistry:
    """Manage one sandbox's registered resources."""

    def __init__(self, sandbox_root: str, default_maintain_interval_sec: float = DEFAULT_MAINTAIN_INTERVAL_SEC):
        self.sandbox_root = os.path.realpath(sandbox_root)
        os.makedirs(self.sandbox_root, exist_ok=True)
        self.default_maintain_interval_sec = float(default_maintain_interval_sec)
        self._handles: dict[str, MaintenanceHandle] = {}
        self._lock = threading.Lock()
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        self._watchdog_interval = 0.0

    @property
    def registry_path(self) -> str:
        return os.path.join(self.sandbox_root, "resources.json")

    def _empty_config(self) -> dict[str, Any]:
        return {
            "default_maintain_interval_sec": self.default_maintain_interval_sec,
            "default_git_auto_commit_daily": False,
            "resources": {},
        }

    def _load(self) -> dict[str, Any]:
        path = self.registry_path
        if not os.path.isfile(path):
            return self._empty_config()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return self._empty_config()
        if not isinstance(data, dict):
            return self._empty_config()
        resources = data.get("resources", {})
        if not isinstance(resources, dict):
            resources = {}
        default_interval = _normalize_interval(data.get("default_maintain_interval_sec"))
        if default_interval is None:
            default_interval = self.default_maintain_interval_sec
        default_git = _normalize_bool(data.get("default_git_auto_commit_daily"))
        if default_git is None:
            default_git = False
        return {
            "default_maintain_interval_sec": default_interval,
            "default_git_auto_commit_daily": default_git,
            "resources": resources,
        }

    def _save(self, data: dict[str, Any]) -> None:
        path = self.registry_path
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)

    def config(self) -> dict[str, Any]:
        return self._load()

    def set_default_maintain_interval(self, interval_sec: float) -> None:
        interval = _normalize_interval(interval_sec)
        if interval is None:
            raise ValueError("default maintain interval must be a non-negative number")
        data = self._load()
        data["default_maintain_interval_sec"] = interval
        self._save(data)

    def set_default_git_auto_commit_daily(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("default git auto commit setting must be boolean")
        data = self._load()
        data["default_git_auto_commit_daily"] = enabled
        self._save(data)

    def register_resource(
        self,
        resource_id: str,
        root: str,
        *,
        resource_type: str = "context_tree",
        config_path: str = "",
        maintain_interval_sec: float | None = None,
        git_auto_commit_daily: bool | None = None,
    ) -> dict[str, Any]:
        resource_id = _validate_resource_id(resource_id)
        resource_root = os.path.realpath(root)
        if not os.path.exists(resource_root):
            raise FileNotFoundError(f"resource root not found: {resource_root}")
        if resource_type == "context_tree" and not os.path.isdir(resource_root):
            raise FileNotFoundError(f"context_tree root not found: {resource_root}")
        interval = _normalize_interval(maintain_interval_sec)
        data = self._load()
        data["resources"][resource_id] = {
            "type": str(resource_type or "context_tree"),
            "root": resource_root,
            "config_path": os.path.realpath(config_path) if config_path else "",
            "maintain_interval_sec": interval,
            "git_auto_commit_daily": _normalize_bool(git_auto_commit_daily),
            "git_last_commit_date": str(data.get("resources", {}).get(resource_id, {}).get("git_last_commit_date") or ""),
        }
        self._save(data)
        return self.get_resource(resource_id)

    def unregister_resource(self, resource_id: str, *, stop_maintenance: bool = False) -> dict[str, Any] | None:
        resource_id = _validate_resource_id(resource_id)
        existing = self.get_resource(resource_id)
        if existing is None:
            return None
        if stop_maintenance:
            self._stop_handle(resource_id)
        data = self._load()
        data.get("resources", {}).pop(resource_id, None)
        self._save(data)
        return existing

    def _effective_interval(self, entry: dict[str, Any], default_interval: float) -> float:
        interval = _normalize_interval(entry.get("maintain_interval_sec"))
        if interval is None:
            return float(default_interval)
        return interval

    def _effective_git_auto_commit(self, entry: dict[str, Any], default_enabled: bool) -> bool:
        enabled = _normalize_bool(entry.get("git_auto_commit_daily"))
        if enabled is None:
            return bool(default_enabled)
        return enabled

    def _status_for_entry(self, resource_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        handle = self._handles.get(resource_id)
        if handle is None:
            return {"running": False, "interval": 0}
        status = handle.status()
        status["interval"] = handle.interval if status.get("running") else 0
        return status

    def get_resource(self, resource_id: str) -> dict[str, Any] | None:
        resource_id = _validate_resource_id(resource_id)
        data = self._load()
        entry = data.get("resources", {}).get(resource_id)
        if not isinstance(entry, dict):
            return None
        root = os.path.realpath(str(entry.get("root") or ""))
        resource_type = str(entry.get("type") or "context_tree")
        return {
            "id": resource_id,
            "type": resource_type,
            "root": root,
            "config_path": str(entry.get("config_path") or ""),
            "maintain_interval_sec": _normalize_interval(entry.get("maintain_interval_sec")),
            "effective_maintain_interval_sec": self._effective_interval(
                entry,
                data.get("default_maintain_interval_sec", self.default_maintain_interval_sec),
            ),
            "git_auto_commit_daily": _normalize_bool(entry.get("git_auto_commit_daily")),
            "effective_git_auto_commit_daily": self._effective_git_auto_commit(
                entry,
                bool(data.get("default_git_auto_commit_daily", False)),
            ),
            "git_last_commit_date": str(entry.get("git_last_commit_date") or ""),
            "summary": _summary_for_root(root) if resource_type == "context_tree" and os.path.isdir(root) else "",
            "maintenance": self._status_for_entry(resource_id, entry),
        }

    def list_resources(self) -> list[dict[str, Any]]:
        data = self._load()
        results: list[dict[str, Any]] = []
        for resource_id in sorted(data.get("resources", {}).keys()):
            item = self.get_resource(resource_id)
            if item is not None:
                results.append(item)
        return results

    def resource_map_for_brain(self, ids: list[str] | None = None) -> dict[str, dict[str, str]]:
        wanted = {str(item) for item in ids or [] if str(item)}
        results: dict[str, dict[str, str]] = {}
        for item in self.list_resources():
            if wanted and item["id"] not in wanted:
                continue
            results[item["id"]] = {
                "type": item["type"],
                "path": item["root"],
                "summary": item["summary"],
            }
        return results

    def _make_tree(self, entry: dict[str, Any]) -> ContexTree:
        return ContexTree(
            entry["root"],
            config_path=entry.get("config_path") or None,
        )

    def _stop_handle(self, resource_id: str) -> None:
        handle = self._handles.pop(resource_id, None)
        if handle is None:
            return
        try:
            handle.stop()
        except Exception:
            pass

    def reconcile_maintenance(self, resource_id: str = "") -> list[dict[str, Any]]:
        targets = [self.get_resource(resource_id)] if resource_id else self.list_resources()
        results: list[dict[str, Any]] = []
        with self._lock:
            for item in targets:
                if item is None:
                    continue
                desired = float(item["effective_maintain_interval_sec"])
                current = self._handles.get(item["id"])
                running = bool(current and current.status().get("running"))
                action = "unchanged"
                if item["type"] != "context_tree":
                    self._stop_handle(item["id"])
                    action = "ignored"
                elif desired <= 0:
                    if running:
                        self._stop_handle(item["id"])
                        action = "stopped"
                    else:
                        action = "disabled"
                else:
                    if current is not None and abs(float(current.interval) - desired) > 1e-9:
                        self._stop_handle(item["id"])
                        current = None
                        running = False
                        action = "restarted"
                    if current is None or not running:
                        handle = start_registered_maintenance(self._make_tree(item), interval=desired)
                        self._handles[item["id"]] = handle
                        action = "started" if action == "unchanged" else action
                refreshed = self.get_resource(item["id"]) or item
                refreshed["action"] = action
                results.append(refreshed)
        return results

    def _git_repo_root(self, root: str) -> str:
        marker = os.path.join(root, ".git")
        return root if os.path.isdir(marker) else ""

    def _run_git(self, cwd: str, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )

    def _run_daily_git_automation(self, resource_id: str) -> dict[str, Any]:
        item = self.get_resource(resource_id)
        if item is None:
            raise FileNotFoundError(f"unknown resource: {resource_id}")
        repo_root = self._git_repo_root(str(item.get("root") or ""))
        if not repo_root:
            return {"ok": False, "reason": "no_git_repo"}
        if not bool(item.get("effective_git_auto_commit_daily")):
            return {"ok": False, "reason": "disabled"}
        today = datetime.now(timezone.utc).date().isoformat()
        if str(item.get("git_last_commit_date") or "") == today:
            return {"ok": False, "reason": "already_ran_today"}

        add = self._run_git(repo_root, ["add", "-A"])
        if add.returncode != 0:
            return {"ok": False, "reason": "git_add_failed", "stderr": add.stderr.strip()}
        diff = self._run_git(repo_root, ["diff", "--cached", "--quiet"])
        if diff.returncode == 0:
            self._mark_git_last_commit_date(resource_id, today)
            return {"ok": True, "reason": "no_changes", "date": today}
        if diff.returncode not in {0, 1}:
            return {"ok": False, "reason": "git_diff_failed", "stderr": diff.stderr.strip()}

        message = f"Hydrai daily checkpoint {today}"
        commit = self._run_git(repo_root, ["commit", "-m", message])
        if commit.returncode != 0:
            return {"ok": False, "reason": "git_commit_failed", "stderr": commit.stderr.strip()}

        push = self._run_git(repo_root, ["push"])
        if push.returncode != 0:
            return {"ok": False, "reason": "git_push_failed", "stderr": push.stderr.strip()}

        self._mark_git_last_commit_date(resource_id, today)
        return {"ok": True, "reason": "pushed", "date": today}

    def _mark_git_last_commit_date(self, resource_id: str, date_text: str) -> None:
        data = self._load()
        entry = data.get("resources", {}).get(resource_id)
        if not isinstance(entry, dict):
            return
        entry["git_last_commit_date"] = date_text
        self._save(data)

    def run_git_automation(self, resource_id: str = "") -> list[dict[str, Any]]:
        targets = [resource_id] if resource_id else [item["id"] for item in self.list_resources()]
        results: list[dict[str, Any]] = []
        with self._lock:
            for item_id in targets:
                try:
                    status = self._run_daily_git_automation(item_id)
                except Exception as exc:
                    status = {"ok": False, "reason": str(exc) or "git_automation_failed"}
                status["id"] = item_id
                results.append(status)
        return results

    def start_watchdog(self, interval: float = 60.0) -> None:
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            raise RuntimeError("resource watchdog already running")
        self._watchdog_interval = float(interval)
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def stop_watchdog(self, timeout: float = 10.0) -> None:
        self._watchdog_stop.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=timeout)
            if not self._watchdog_thread.is_alive():
                self._watchdog_thread = None

    def watchdog_status(self) -> dict[str, Any]:
        running = self._watchdog_thread is not None and self._watchdog_thread.is_alive()
        return {
            "running": running,
            "interval": self._watchdog_interval if running else 0,
        }

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.is_set():
            try:
                self.reconcile_maintenance()
            except Exception:
                pass
            try:
                self.run_git_automation()
            except Exception:
                pass
            self._watchdog_stop.wait(timeout=self._watchdog_interval)

    def stop_all_maintenance(self) -> None:
        self.stop_watchdog()
        with self._lock:
            ids = list(self._handles.keys())
            for resource_id in ids:
                self._stop_handle(resource_id)
