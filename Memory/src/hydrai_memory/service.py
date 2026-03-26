"""HTTP server lifecycle for the Memory service."""

from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Callable

from hydrai_memory.auth import InternalAuthGate
from hydrai_memory.brain_bootstrap import BrainBootstrapAPI
from hydrai_memory.config import SandboxConfig, ServiceConfig
from hydrai_memory.identity_state import IdentityBrainAPI, IdentityStore
from hydrai_memory.policy import SandboxPolicy
from hydrai_memory.resources import MemorySandboxAPI, ResourceRegistry
from hydrai_memory.sessionbook import SessionBrainAPI, SessionStore
from hydrai_memory.skillset import SkillManager

LOG = logging.getLogger("hydrai_memory.service")


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _split_path(path: str) -> list[str]:
    return [part for part in str(path or "").split("?")[0].split("/") if part]


def _manual_path() -> str:
    env_path = os.environ.get("HYDRAI_MEMORY_MANUAL_PATH", "").strip()
    if env_path:
        return os.path.realpath(os.path.expanduser(env_path))
    try:
        candidate = resources.files("hydrai_memory").joinpath("MANUAL.md")
        if candidate.is_file():
            return str(candidate)
    except Exception:
        pass
    return ""


class SandboxRuntime:
    def __init__(self, service_config: ServiceConfig, sandbox_config: SandboxConfig):
        self.service_config = service_config
        self.sandbox_config = sandbox_config
        self._mutation_lock = threading.Lock()
        self.resource_registry = ResourceRegistry(self.sandbox_root)
        self.policy = SandboxPolicy(
            self.service_config.storage_root,
            self.sandbox_config.sandbox_id,
            sandbox_skill_whitelist=self.sandbox_config.skill_whitelist,
            sandbox_skill_blacklist=self.sandbox_config.skill_blacklist,
        )
        self.identity_store = IdentityStore(
            self.service_config.storage_root,
            self.sandbox_config.sandbox_id,
            config_path=self.service_config.config_path,
        )
        self.identity_brain = IdentityBrainAPI(self.identity_store)
        self.session_store = SessionStore(
            self.service_config.storage_root,
            self.sandbox_config.sandbox_id,
            config_path=self.service_config.config_path,
        )
        self.session_brain = SessionBrainAPI(self.session_store)
        self.skill_manager = SkillManager(
            self.service_config.storage_root,
            self.sandbox_config.sandbox_id,
            trusted_hubs=self.service_config.trusted_skill_hubs,
            config_path=self.service_config.config_path,
            sandbox_skill_whitelist=self.sandbox_config.skill_whitelist,
            sandbox_skill_blacklist=self.sandbox_config.skill_blacklist,
        )
        self.skill_manager.initialize_defaults()
        self.brain_bootstrap = BrainBootstrapAPI(
            self.identity_store,
            self.identity_brain,
            self.session_brain,
            self.resource_registry,
            self.skill_manager,
        )
        self.tree_api_control = MemorySandboxAPI(
            self.service_config.storage_root,
            self.sandbox_config.sandbox_id,
            sandbox_space_root=self.sandbox_config.sandbox_space_root,
            system_access=True,
            config_path=self.service_config.config_path,
        )
        self.tree_api_sandbox = MemorySandboxAPI(
            self.service_config.storage_root,
            self.sandbox_config.sandbox_id,
            sandbox_space_root=self.sandbox_config.sandbox_space_root,
            system_access=False,
            config_path=self.service_config.config_path,
        )
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def sandbox_root(self) -> str:
        return f"{self.service_config.storage_root}/sandboxes/{self.sandbox_config.sandbox_id}"

    def mutate(self, fn: Callable[[], Any]) -> Any:
        with self._mutation_lock:
            return fn()

    def help_payload(self, actual_port: int) -> dict[str, Any]:
        return {
            "service": "Hydrai Memory",
            "scope": "sandbox",
            "sandbox_id": self.sandbox_config.sandbox_id,
            "port": actual_port,
            "storage_root": self.service_config.storage_root,
            "sandbox_space_root": self.sandbox_config.sandbox_space_root,
            "context_defaults_source": self.service_config.config_path,
            "watchdog": self.resource_registry.watchdog_status(),
            "manual_path": _manual_path(),
            "endpoints": {
                "health": "GET /health",
                "help": "GET /help",
                "tree_view": "POST /tree/view",
                "tree_read": "POST /tree/read",
                "tree_search": "POST /tree/search",
                "tree_write": "POST /tree/write",
                "tree_append": "POST /tree/append",
                "tree_delete": "POST /tree/delete",
                "resource_list": "POST /resources/list",
                "brain_bootstrap": "POST /brain/bootstrap",
                "identity_relations": "POST /identity/relations",
                "identity_sessions": "POST /identity/sessions",
                "identity_memorables_search": "POST /identity/memorables-search",
                "session_recent": "POST /session/recent",
                "session_search": "POST /session/search",
                "session_latest_attachments": "POST /session/latest-attachments",
                "skill_list": "POST /skills/list",
                "skill_search": "POST /skills/search",
                "skill_read": "POST /skills/read",
                "trusted_skill_sites": "POST /skills/trusted-sites",
                "skill_install": "POST /skills/install",
            },
        }


class MemoryService:
    def __init__(self, config: ServiceConfig, auth_gate: InternalAuthGate):
        self._config = config
        self._auth_gate = auth_gate
        self._sandboxes = {
            item.sandbox_id: SandboxRuntime(config, item)
            for item in config.sandboxes
        }
        self._control_server: ThreadingHTTPServer | None = None
        self._control_thread: threading.Thread | None = None

    def _require_auth(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._auth_gate.check(
            handler.headers.get("X-Hydrai-Token-Id"),
            handler.headers.get("X-Hydrai-Token"),
        ):
            raise HttpError(401, "unauthorized")

    def _read_json(self, handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        length = int(handler.headers.get("Content-Length", "0") or "0")
        raw = handler.rfile.read(length) if length > 0 else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise HttpError(400, "request body must be a JSON object")
        return data

    def _json(self, handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _error_status(self, exc: Exception) -> int:
        if isinstance(exc, HttpError):
            return exc.status
        if isinstance(exc, FileNotFoundError):
            return 404
        if isinstance(exc, KeyError):
            return 404
        if isinstance(exc, PermissionError):
            return 403
        if isinstance(exc, FileExistsError):
            return 409
        if isinstance(exc, RuntimeError):
            return 409
        if isinstance(exc, ValueError):
            return 400
        return 500

    def _error_payload(self, exc: Exception) -> dict[str, Any]:
        if isinstance(exc, HttpError):
            return {"error": exc.message}
        return {"error": str(exc) or "internal server error"}

    def _handle_errors(self, handler: BaseHTTPRequestHandler, fn: Callable[[], None]) -> None:
        try:
            fn()
        except json.JSONDecodeError:
            self._json(handler, 400, {"error": "invalid json"})
        except ValueError as exc:
            self._json(handler, 400, {"error": str(exc)})
        except Exception as exc:
            status = self._error_status(exc)
            if status >= 500:
                LOG.exception("unhandled Memory service error")
            self._json(handler, status, self._error_payload(exc))

    def _lookup_sandbox(self, sandbox_id: str) -> SandboxRuntime:
        item = self._sandboxes.get(str(sandbox_id))
        if item is None:
            raise HttpError(404, f"unknown sandbox: {sandbox_id}")
        return item

    def _tree_api(self, sandbox: SandboxRuntime, sandbox_scope: bool) -> MemorySandboxAPI:
        return sandbox.tree_api_sandbox if sandbox_scope else sandbox.tree_api_control

    def _help_payload(self) -> dict[str, Any]:
        return {
            "service": "Hydrai Memory",
            "security_mode": self._auth_gate.mode,
            "config_path": self._config.config_path,
            "storage_root": self._config.storage_root,
            "manual_path": _manual_path(),
            "control_port": self._control_server.server_address[1] if self._control_server else self._config.control_port,
            "sandboxes": [
                {
                    "id": item.sandbox_config.sandbox_id,
                    "port": item.server.server_address[1] if item.server is not None else item.sandbox_config.port,
                    "sandbox_space_root": item.sandbox_config.sandbox_space_root,
                    "context_defaults_source": self._config.config_path,
                    "watchdog": item.resource_registry.watchdog_status(),
                }
                for item in self._sandboxes.values()
            ],
            "trusted_skill_hubs": [
                {
                    "id": hub.hub_id,
                    "index_url": hub.index_url,
                    "site_url": hub.site_url,
                    "description": hub.description,
                }
                for hub in self._config.trusted_skill_hubs
            ],
            "usage": {
                "startup": "hydrai-memory --config ~/Public/hydrai/Memory.json",
                "control": {
                    "health": "GET /health",
                    "help": "GET /help",
                    "list_sandboxes": "GET /sandboxes",
                    "sandbox_prefix": "/sandboxes/{sandbox_id}/...",
                },
            },
        }

    def _dispatch_tree(self, sandbox: SandboxRuntime, sandbox_scope: bool, action: str, body: dict[str, Any]) -> Any:
        api = self._tree_api(sandbox, sandbox_scope)
        actor_identity_id = str(body.get("actor_identity_id") or "")
        session_id = str(body.get("session_id") or "")
        if action == "view":
            return api.view(
                target_type=str(body.get("target_type") or ""),
                target_id=str(body.get("target_id") or ""),
                path=str(body.get("path") or ""),
                depth=int(body.get("depth", 2)),
                summary_depth=int(body.get("summary_depth", 1)),
                actor_identity_id=actor_identity_id,
                session_id=session_id,
            )
        if action == "read":
            return api.read(
                target_type=str(body.get("target_type") or ""),
                target_id=str(body.get("target_id") or ""),
                paths=list(body.get("paths") or []),
                actor_identity_id=actor_identity_id,
                session_id=session_id,
            )
        if action == "search":
            return api.search(
                target_type=str(body.get("target_type") or ""),
                target_id=str(body.get("target_id") or ""),
                query_text=body.get("query_text"),
                query_embed=body.get("query_embed"),
                top_k=int(body.get("top_k", 10)),
                min_score=float(body.get("min_score", 0.3)),
                paths=list(body.get("paths") or []) if body.get("paths") is not None else None,
                actor_identity_id=actor_identity_id,
                session_id=session_id,
            )
        if action == "write":
            return sandbox.mutate(
                lambda: api.write(
                    target_type=str(body.get("target_type") or ""),
                    target_id=str(body.get("target_id") or ""),
                    path=str(body.get("path") or ""),
                    content=str(body.get("content") or ""),
                    summary=str(body.get("summary") or ""),
                    actor_identity_id=actor_identity_id,
                    session_id=session_id,
                )
            )
        if action == "append":
            return sandbox.mutate(
                lambda: api.append(
                    target_type=str(body.get("target_type") or ""),
                    target_id=str(body.get("target_id") or ""),
                    path=str(body.get("path") or ""),
                    content=str(body.get("content") or ""),
                    summary=str(body.get("summary") or ""),
                    actor_identity_id=actor_identity_id,
                    session_id=session_id,
                )
            )
        if action == "delete":
            return sandbox.mutate(
                lambda: api.delete(
                    target_type=str(body.get("target_type") or ""),
                    target_id=str(body.get("target_id") or ""),
                    path=str(body.get("path") or ""),
                    actor_identity_id=actor_identity_id,
                    session_id=session_id,
                )
            )
        raise HttpError(404, "not found")

    def _require_identity_self_access(self, sandbox: SandboxRuntime, identity_id: str, actor_identity_id: str) -> None:
        sandbox.policy.authorize_tree(
            target_type="identity",
            target_id=identity_id,
            actor_identity_id=actor_identity_id,
            embedder=sandbox.tree_api_sandbox.embedder,
            config_path=sandbox.service_config.config_path,
        )

    def _require_known_actor(self, sandbox: SandboxRuntime, actor_identity_id: str) -> None:
        actor = str(actor_identity_id or "").strip()
        if not actor:
            raise ValueError("actor_identity_id is required")
        if not sandbox.policy.identity_like_exists(actor):
            raise FileNotFoundError(f"unknown actor identity: {actor}")

    def _dispatch_identity_brain(self, sandbox: SandboxRuntime, action: str, body: dict[str, Any]) -> Any:
        api = sandbox.identity_brain
        actor_identity_id = str(body.get("actor_identity_id") or "")
        self._require_identity_self_access(sandbox, actor_identity_id, actor_identity_id)
        if action == "relations":
            return api.identity_relations(actor_identity_id, list(body.get("friend_ids") or []))
        if action == "sessions":
            return api.identity_sessions(actor_identity_id, list(body.get("session_ids") or []))
        if action == "memorables-search":
            return api.identity_memorables_search(
                actor_identity_id,
                str(body.get("query") or ""),
                top_content_n=int(body.get("top_content_n", 3)),
                top_summary_k=int(body.get("top_summary_k", 5)),
                min_score=float(body.get("min_score", 0.3)),
            )
        raise HttpError(404, "not found")

    def _dispatch_session_brain(self, sandbox: SandboxRuntime, action: str, body: dict[str, Any]) -> Any:
        api = sandbox.session_brain
        session_id = str(body.get("session_id") or "")
        actor_identity_id = str(body.get("actor_identity_id") or "")
        sandbox.policy.authorize_tree(
            target_type="session",
            target_id=session_id,
            actor_identity_id=actor_identity_id,
            embedder=sandbox.tree_api_sandbox.embedder,
            config_path=sandbox.service_config.config_path,
        )
        if action == "recent":
            return api.session_recent(
                session_id,
                query=str(body.get("query") or ""),
                top_k=int(body.get("top_k", 10)),
                min_score=float(body.get("min_score", 0.3)),
            )
        if action == "search":
            return api.session_search_text(
                session_id,
                str(body.get("query") or ""),
                top_k=int(body.get("top_k", 10)),
                min_score=float(body.get("min_score", 0.3)),
            )
        if action == "latest-attachments":
            return api.session_latest_attachments(
                session_id,
                limit=int(body.get("limit", 10)),
            )
        raise HttpError(404, "not found")

    def _require_skill_capability(self, sandbox: SandboxRuntime, actor_identity_id: str, capability_name: str) -> None:
        if not sandbox.skill_manager.capability_allowed(actor_identity_id, capability_name):
            raise PermissionError(f"identity may not use capability: {capability_name}")

    def _dispatch_skill_brain(self, sandbox: SandboxRuntime, action: str, body: dict[str, Any]) -> Any:
        manager = sandbox.skill_manager
        actor_identity_id = str(body.get("actor_identity_id") or "")
        self._require_known_actor(sandbox, actor_identity_id)
        if action == "list":
            return manager.skill_list(actor_identity_id)
        if action == "search":
            return manager.skill_search(
                actor_identity_id,
                str(body.get("query") or ""),
                limit=int(body.get("limit", 10)),
                min_score=float(body.get("min_score", 0.3)),
            )
        if action == "read":
            return manager.skill_read(
                actor_identity_id,
                str(body.get("name") or ""),
                category=str(body.get("category") or ""),
            )
        if action == "trusted-sites":
            self._require_skill_capability(sandbox, actor_identity_id, "install_skill")
            return {"results": manager.list_trusted_sites()}
        if action == "install":
            self._require_skill_capability(sandbox, actor_identity_id, "install_skill")
            return sandbox.mutate(
                lambda: manager.install_skill(
                    actor_identity_id,
                    str(body.get("hub_id") or ""),
                    str(body.get("skill_name") or ""),
                    force=bool(body.get("force", False)),
                )
            )
        raise HttpError(404, "not found")

    def _dispatch_brain_api(self, sandbox: SandboxRuntime, action: str, body: dict[str, Any]) -> Any:
        if action == "bootstrap":
            actor_identity_id = str(body.get("actor_identity_id") or "")
            sandbox.policy.authorize_tree(
                target_type="identity",
                target_id=actor_identity_id,
                actor_identity_id=actor_identity_id,
                embedder=sandbox.tree_api_sandbox.embedder,
                config_path=sandbox.service_config.config_path,
            )
            session_id = str(body.get("session_id") or "")
            if session_id:
                sandbox.policy.authorize_tree(
                    target_type="session",
                    target_id=session_id,
                    actor_identity_id=actor_identity_id,
                    embedder=sandbox.tree_api_sandbox.embedder,
                    config_path=sandbox.service_config.config_path,
                )
            return sandbox.brain_bootstrap.bootstrap(
                actor_identity_id,
                requestor_id=str(body.get("requestor_id") or ""),
                session_id=session_id,
                query=str(body.get("query") or ""),
                top_k=int(body.get("top_k", 10)),
                min_score=float(body.get("min_score", 0.3)),
                attachment_limit=int(body.get("attachment_limit", 5)),
            )
        raise HttpError(404, "not found")

    def _dispatch_resource_brain(self, sandbox: SandboxRuntime, action: str, body: dict[str, Any]) -> Any:
        if action == "list":
            return sandbox.policy.list_accessible_targets(
                actor_identity_id=str(body.get("actor_identity_id") or ""),
                registry=sandbox.resource_registry,
                session_id=str(body.get("session_id") or ""),
                embedder=sandbox.tree_api_sandbox.embedder,
                config_path=sandbox.service_config.config_path,
                identity_store=sandbox.identity_store,
            )
        raise HttpError(404, "not found")

    def _dispatch_control_get(self, parts: list[str]) -> Any:
        if parts == ["health"]:
            return {"status": "ok", "service": "memory", "port": self._control_server.server_address[1] if self._control_server else self._config.control_port}
        if parts == ["help"]:
            return self._help_payload()
        if parts == ["sandboxes"]:
            return {
                "sandboxes": [
                    {
                        "id": item.sandbox_config.sandbox_id,
                        "port": item.server.server_address[1] if item.server is not None else item.sandbox_config.port,
                    }
                    for item in self._sandboxes.values()
                ]
            }
        if len(parts) >= 2 and parts[0] == "sandboxes":
            sandbox = self._lookup_sandbox(parts[1])
            rest = parts[2:]
            if rest == ["resources"]:
                return {"resources": sandbox.resource_registry.list_resources()}
            if len(rest) == 2 and rest[0] == "resources":
                item = sandbox.resource_registry.get_resource(rest[1])
                if item is None:
                    raise HttpError(404, "unknown resource")
                return item
            if rest == ["resources", "watchdog"]:
                return sandbox.resource_registry.watchdog_status()
            if rest == ["identities"]:
                return {"identities": sandbox.identity_store.list_identities()}
            if len(rest) == 2 and rest[0] == "identities":
                item = sandbox.identity_store.get_identity(rest[1])
                if item is None:
                    raise HttpError(404, "unknown identity")
                return item
            if rest == ["humans"]:
                return {"humans": sandbox.identity_store.list_humans()}
            if len(rest) == 2 and rest[0] == "humans":
                item = sandbox.identity_store.get_human(rest[1])
                if item is None:
                    raise HttpError(404, "unknown human")
                return item
            if rest == ["native"]:
                return {"native": sandbox.identity_store.list_native()}
            if len(rest) == 2 and rest[0] == "native":
                item = sandbox.identity_store.get_native(rest[1])
                if item is None:
                    raise HttpError(404, "unknown native")
                return item
            if rest == ["sessions"]:
                return {"sessions": sandbox.session_store.list_sessions()}
            if len(rest) == 2 and rest[0] == "sessions":
                item = sandbox.session_store.get_session(rest[1])
                if item is None:
                    raise HttpError(404, "unknown session")
                return item
            if rest == ["skills", "trusted-sites"]:
                return {"results": sandbox.skill_manager.list_trusted_sites()}
        raise HttpError(404, "not found")

    def _dispatch_control_post(self, parts: list[str], body: dict[str, Any]) -> Any:
        if len(parts) < 2 or parts[0] != "sandboxes":
            raise HttpError(404, "not found")
        sandbox = self._lookup_sandbox(parts[1])
        rest = parts[2:]
        if len(rest) == 2 and rest[0] == "tree":
            return self._dispatch_tree(sandbox, False, rest[1], body)
        if len(rest) == 3 and rest[0] == "brain" and rest[1] == "identity":
            return self._dispatch_identity_brain(sandbox, rest[2], body)
        if len(rest) == 3 and rest[0] == "brain" and rest[1] == "session":
            return self._dispatch_session_brain(sandbox, rest[2], body)
        if len(rest) == 3 and rest[0] == "brain" and rest[1] == "skills":
            return self._dispatch_skill_brain(sandbox, rest[2], body)
        if rest == ["resources", "register"]:
            return sandbox.mutate(
                lambda: sandbox.resource_registry.register_resource(
                    str(body.get("resource_id") or ""),
                    str(body.get("root") or ""),
                    resource_type=str(body.get("resource_type") or "context_tree"),
                    config_path=str(body.get("config_path") or ""),
                    maintain_interval_sec=body.get("maintain_interval_sec"),
                    git_auto_commit_daily=body.get("git_auto_commit_daily"),
                )
            )
        if rest == ["resources", "unregister"]:
            return sandbox.mutate(
                lambda: {
                    "removed": sandbox.resource_registry.unregister_resource(
                        str(body.get("resource_id") or ""),
                        stop_maintenance=bool(body.get("stop_maintenance", False)),
                    )
                }
            )
        if rest == ["resources", "reconcile"]:
            return sandbox.mutate(
                lambda: {
                    "results": sandbox.resource_registry.reconcile_maintenance(str(body.get("resource_id") or ""))
                }
            )
        if rest == ["resources", "watchdog", "start"]:
            return sandbox.mutate(
                lambda: (
                    sandbox.resource_registry.start_watchdog(float(body.get("interval", 60.0))),
                    sandbox.resource_registry.watchdog_status(),
                )[1]
            )
        if rest == ["resources", "watchdog", "stop"]:
            return sandbox.mutate(
                lambda: (
                    sandbox.resource_registry.stop_watchdog(),
                    sandbox.resource_registry.watchdog_status(),
                )[1]
            )
        if rest == ["resources", "watchdog", "defaults"]:
            def _set_defaults():
                if "interval" in body:
                    sandbox.resource_registry.set_default_maintain_interval(float(body.get("interval", 0)))
                if "git_auto_commit_daily" in body:
                    sandbox.resource_registry.set_default_git_auto_commit_daily(bool(body.get("git_auto_commit_daily")))
                return sandbox.resource_registry.watchdog_status()
            return sandbox.mutate(_set_defaults)
        if rest == ["resources", "git-run"]:
            return sandbox.mutate(
                lambda: {
                    "results": sandbox.resource_registry.run_git_automation(str(body.get("resource_id") or ""))
                }
            )
        if rest == ["identities", "create"]:
            return sandbox.mutate(
                lambda: sandbox.identity_store.create_identity(
                    str(body.get("identity_id") or ""),
                    str(body.get("persona") or ""),
                    str(body.get("soul") or ""),
                    dict(body.get("config") or {}),
                )
            )
        if len(rest) == 3 and rest[0] == "identities" and rest[2] == "persona":
            return sandbox.mutate(
                lambda: sandbox.identity_store.set_identity_persona(rest[1], str(body.get("content") or ""))
            )
        if len(rest) == 3 and rest[0] == "identities" and rest[2] == "soul":
            return sandbox.mutate(
                lambda: sandbox.identity_store.set_identity_soul(rest[1], str(body.get("content") or ""))
            )
        if len(rest) == 3 and rest[0] == "identities" and rest[2] == "config":
            return sandbox.mutate(
                lambda: sandbox.identity_store.set_identity_config(rest[1], dict(body.get("config") or {}))
            )
        if rest == ["humans", "create"]:
            return sandbox.mutate(
                lambda: sandbox.identity_store.create_human(
                    str(body.get("identity_id") or ""),
                    str(body.get("persona") or ""),
                )
            )
        if len(rest) == 3 and rest[0] == "humans" and rest[2] == "persona":
            return sandbox.mutate(
                lambda: sandbox.identity_store.set_human_persona(rest[1], str(body.get("content") or ""))
            )
        if rest == ["sessions", "create"]:
            return sandbox.mutate(
                lambda: sandbox.session_store.create_session(
                    str(body.get("session_id") or ""),
                    dict(body.get("identities") or {}),
                    dict(body.get("resources") or {}),
                    channel=str(body.get("channel") or ""),
                    brain=dict(body.get("brain") or {}),
                    limits=dict(body.get("limits") or {}),
                )
            )
        if len(rest) == 3 and rest[0] == "sessions" and rest[2] == "invite":
            return sandbox.mutate(
                lambda: sandbox.session_store.invite_identity(
                    rest[1],
                    str(body.get("identity_id") or ""),
                    str(body.get("mode") or "rw"),
                )
            )
        if len(rest) == 3 and rest[0] == "sessions" and rest[2] == "kick":
            return sandbox.mutate(
                lambda: sandbox.session_store.kick_identity(rest[1], str(body.get("identity_id") or ""))
            )
        if len(rest) == 3 and rest[0] == "sessions" and rest[2] == "mount":
            return sandbox.mutate(
                lambda: sandbox.session_store.mount_resource(
                    rest[1],
                    str(body.get("resource_id") or ""),
                    str(body.get("mode") or "rw"),
                )
            )
        if len(rest) == 3 and rest[0] == "sessions" and rest[2] == "unmount":
            return sandbox.mutate(
                lambda: sandbox.session_store.unmount_resource(rest[1], str(body.get("resource_id") or ""))
            )
        if len(rest) == 3 and rest[0] == "sessions" and rest[2] == "attach":
            return sandbox.mutate(
                lambda: sandbox.session_store.attach_file(
                    rest[1],
                    str(body.get("source_path") or ""),
                    str(body.get("sender") or ""),
                    summary=str(body.get("summary") or ""),
                )
            )
        if len(rest) == 3 and rest[0] == "sessions" and rest[2] == "append":
            return sandbox.mutate(
                lambda: sandbox.session_store.append_turn(rest[1], str(body.get("text") or ""))
            )
        if len(rest) == 3 and rest[0] == "sessions" and rest[2] == "break":
            return sandbox.mutate(lambda: sandbox.session_store.break_chapter(rest[1]))
        if rest == ["skills", "initialize"]:
            return sandbox.mutate(lambda: sandbox.skill_manager.initialize_defaults())
        raise HttpError(404, "not found")

    def _dispatch_control_delete(self, parts: list[str]) -> Any:
        if len(parts) < 2 or parts[0] != "sandboxes":
            raise HttpError(404, "not found")
        sandbox = self._lookup_sandbox(parts[1])
        rest = parts[2:]
        if len(rest) == 2 and rest[0] == "identities":
            return sandbox.mutate(lambda: {"removed": sandbox.identity_store.delete_identity(rest[1])})
        if len(rest) == 2 and rest[0] == "humans":
            return sandbox.mutate(lambda: {"removed": sandbox.identity_store.delete_human(rest[1])})
        if len(rest) == 2 and rest[0] == "sessions":
            return sandbox.mutate(lambda: {"removed": sandbox.session_store.delete_session(rest[1])})
        raise HttpError(404, "not found")

    def _dispatch_sandbox_get(self, sandbox: SandboxRuntime, parts: list[str]) -> Any:
        if parts == ["health"]:
            return {"status": "ok", "service": "memory", "scope": "sandbox", "sandbox_id": sandbox.sandbox_config.sandbox_id, "port": sandbox.server.server_address[1] if sandbox.server else sandbox.sandbox_config.port}
        if parts == ["help"]:
            return sandbox.help_payload(sandbox.server.server_address[1] if sandbox.server else sandbox.sandbox_config.port)
        raise HttpError(404, "not found")

    def _dispatch_sandbox_post(self, sandbox: SandboxRuntime, parts: list[str], body: dict[str, Any]) -> Any:
        if len(parts) == 2 and parts[0] == "tree":
            return self._dispatch_tree(sandbox, True, parts[1], body)
        if len(parts) == 2 and parts[0] == "resources":
            return self._dispatch_resource_brain(sandbox, parts[1], body)
        if len(parts) == 2 and parts[0] == "identity":
            return self._dispatch_identity_brain(sandbox, parts[1], body)
        if len(parts) == 2 and parts[0] == "session":
            return self._dispatch_session_brain(sandbox, parts[1], body)
        if len(parts) == 2 and parts[0] == "brain":
            return self._dispatch_brain_api(sandbox, parts[1], body)
        if len(parts) == 2 and parts[0] == "skills":
            return self._dispatch_skill_brain(sandbox, parts[1], body)
        raise HttpError(404, "not found")

    def _make_control_handler(self):
        service = self

        class ControlHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                service._handle_errors(self, self._handle_get)

            def do_POST(self):
                service._handle_errors(self, self._handle_post)

            def do_DELETE(self):
                service._handle_errors(self, self._handle_delete)

            def _handle_get(self):
                service._require_auth(self)
                payload = service._dispatch_control_get(_split_path(self.path))
                service._json(self, 200, payload)

            def _handle_post(self):
                service._require_auth(self)
                body = service._read_json(self)
                payload = service._dispatch_control_post(_split_path(self.path), body)
                service._json(self, 200, payload)

            def _handle_delete(self):
                service._require_auth(self)
                payload = service._dispatch_control_delete(_split_path(self.path))
                service._json(self, 200, payload)

            def log_message(self, fmt: str, *args):
                LOG.info("[memory-control:%s] " + fmt, service._control_server.server_address[1] if service._control_server else service._config.control_port, *args)

        return ControlHandler

    def _make_sandbox_handler(self, sandbox: SandboxRuntime):
        service = self

        class SandboxHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                service._handle_errors(self, self._handle_get)

            def do_POST(self):
                service._handle_errors(self, self._handle_post)

            def _handle_get(self):
                service._require_auth(self)
                payload = service._dispatch_sandbox_get(sandbox, _split_path(self.path))
                service._json(self, 200, payload)

            def _handle_post(self):
                service._require_auth(self)
                body = service._read_json(self)
                payload = service._dispatch_sandbox_post(sandbox, _split_path(self.path), body)
                service._json(self, 200, payload)

            def log_message(self, fmt: str, *args):
                LOG.info("[memory-sandbox:%s:%s] " + fmt, sandbox.sandbox_config.sandbox_id, sandbox.server.server_address[1] if sandbox.server else sandbox.sandbox_config.port, *args)

        return SandboxHandler

    def start(self) -> None:
        started: list[SandboxRuntime] = []
        try:
            self._control_server = ThreadingHTTPServer(("127.0.0.1", self._config.control_port), self._make_control_handler())
            self._control_thread = threading.Thread(target=self._control_server.serve_forever, daemon=True, name="memory-control")
            self._control_thread.start()
            LOG.info("started Memory control server on :%s", self._control_server.server_address[1])
            for sandbox in self._sandboxes.values():
                sandbox.server = ThreadingHTTPServer(("127.0.0.1", sandbox.sandbox_config.port), self._make_sandbox_handler(sandbox))
                sandbox.thread = threading.Thread(
                    target=sandbox.server.serve_forever,
                    daemon=True,
                    name=f"memory-sandbox-{sandbox.sandbox_config.sandbox_id}",
                )
                sandbox.thread.start()
                started.append(sandbox)
                LOG.info("started Memory sandbox server %s on :%s", sandbox.sandbox_config.sandbox_id, sandbox.server.server_address[1])
        except Exception:
            for sandbox in reversed(started):
                if sandbox.server is not None:
                    sandbox.server.shutdown()
                    sandbox.server.server_close()
                    sandbox.server = None
                    sandbox.thread = None
            if self._control_server is not None:
                self._control_server.shutdown()
                self._control_server.server_close()
                self._control_server = None
                self._control_thread = None
            raise

    def wait(self) -> None:
        if self._control_thread is not None:
            self._control_thread.join()
        for sandbox in self._sandboxes.values():
            if sandbox.thread is not None:
                sandbox.thread.join()

    def stop(self) -> None:
        for sandbox in self._sandboxes.values():
            sandbox.resource_registry.stop_all_maintenance()
            if sandbox.server is not None:
                sandbox.server.shutdown()
                sandbox.server.server_close()
                sandbox.server = None
                sandbox.thread = None
        if self._control_server is not None:
            self._control_server.shutdown()
            self._control_server.server_close()
            self._control_server = None
            self._control_thread = None
