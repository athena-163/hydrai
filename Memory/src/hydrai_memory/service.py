"""HTTP server lifecycle for the Memory service."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from hydrai_memory.auth import InternalAuthGate
from hydrai_memory.config import SandboxConfig, ServiceConfig
from hydrai_memory.identity_state import IdentityBrainAPI, IdentityStore
from hydrai_memory.resources import MemorySandboxAPI, ResourceRegistry
from hydrai_memory.sessionbook import SessionBrainAPI, SessionStore

LOG = logging.getLogger("hydrai_memory.service")


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _split_path(path: str) -> list[str]:
    return [part for part in str(path or "").split("?")[0].split("/") if part]


class SandboxRuntime:
    def __init__(self, service_config: ServiceConfig, sandbox_config: SandboxConfig):
        self.service_config = service_config
        self.sandbox_config = sandbox_config
        self._mutation_lock = threading.Lock()
        self.resource_registry = ResourceRegistry(self.sandbox_root)
        self.identity_store = IdentityStore(
            self.service_config.storage_root,
            self.sandbox_config.sandbox_id,
            config_path=self.sandbox_config.context_config_path or None,
        )
        self.identity_brain = IdentityBrainAPI(self.identity_store)
        self.session_store = SessionStore(
            self.service_config.storage_root,
            self.sandbox_config.sandbox_id,
            config_path=self.sandbox_config.context_config_path or None,
        )
        self.session_brain = SessionBrainAPI(self.session_store)
        self.tree_api_control = MemorySandboxAPI(
            self.service_config.storage_root,
            self.sandbox_config.sandbox_id,
            sandbox_space_root=self.sandbox_config.sandbox_space_root,
            system_access=True,
            config_path=self.sandbox_config.context_config_path or None,
        )
        self.tree_api_sandbox = MemorySandboxAPI(
            self.service_config.storage_root,
            self.sandbox_config.sandbox_id,
            sandbox_space_root=self.sandbox_config.sandbox_space_root,
            system_access=False,
            config_path=self.sandbox_config.context_config_path or None,
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
            "context_config_path": self.sandbox_config.context_config_path,
            "endpoints": {
                "health": "GET /health",
                "help": "GET /help",
                "tree_view": "POST /tree/view",
                "tree_read": "POST /tree/read",
                "tree_search": "POST /tree/search",
                "tree_write": "POST /tree/write",
                "tree_append": "POST /tree/append",
                "tree_delete": "POST /tree/delete",
                "identity_profile": "POST /identity/profile",
                "identity_relations": "POST /identity/relations",
                "identity_sessions": "POST /identity/sessions",
                "identity_memorables_search": "POST /identity/memorables-search",
                "session_recent": "POST /session/recent",
                "session_search": "POST /session/search",
                "session_latest_attachments": "POST /session/latest-attachments",
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
            "control_port": self._control_server.server_address[1] if self._control_server else self._config.control_port,
            "sandboxes": [
                {
                    "id": item.sandbox_config.sandbox_id,
                    "port": item.server.server_address[1] if item.server is not None else item.sandbox_config.port,
                    "sandbox_space_root": item.sandbox_config.sandbox_space_root,
                    "context_config_path": item.sandbox_config.context_config_path,
                }
                for item in self._sandboxes.values()
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
        if action == "view":
            return api.view(
                target_type=str(body.get("target_type") or ""),
                target_id=str(body.get("target_id") or ""),
                path=str(body.get("path") or ""),
                depth=int(body.get("depth", 2)),
                summary_depth=int(body.get("summary_depth", 1)),
            )
        if action == "read":
            return api.read(
                target_type=str(body.get("target_type") or ""),
                target_id=str(body.get("target_id") or ""),
                paths=list(body.get("paths") or []),
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
            )
        if action == "write":
            return sandbox.mutate(
                lambda: api.write(
                    target_type=str(body.get("target_type") or ""),
                    target_id=str(body.get("target_id") or ""),
                    path=str(body.get("path") or ""),
                    content=str(body.get("content") or ""),
                    summary=str(body.get("summary") or ""),
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
                )
            )
        if action == "delete":
            return sandbox.mutate(
                lambda: api.delete(
                    target_type=str(body.get("target_type") or ""),
                    target_id=str(body.get("target_id") or ""),
                    path=str(body.get("path") or ""),
                )
            )
        raise HttpError(404, "not found")

    def _dispatch_identity_brain(self, sandbox: SandboxRuntime, action: str, body: dict[str, Any]) -> Any:
        api = sandbox.identity_brain
        if action == "profile":
            return api.identity_profile(str(body.get("identity_id") or ""))
        if action == "relations":
            return api.identity_relations(str(body.get("identity_id") or ""), list(body.get("friend_ids") or []))
        if action == "sessions":
            return api.identity_sessions(str(body.get("identity_id") or ""), list(body.get("session_ids") or []))
        if action == "memorables-search":
            return api.identity_memorables_search(
                str(body.get("identity_id") or ""),
                str(body.get("query") or ""),
                top_content_n=int(body.get("top_content_n", 3)),
                top_summary_k=int(body.get("top_summary_k", 5)),
                min_score=float(body.get("min_score", 0.3)),
            )
        raise HttpError(404, "not found")

    def _dispatch_session_brain(self, sandbox: SandboxRuntime, action: str, body: dict[str, Any]) -> Any:
        api = sandbox.session_brain
        if action == "recent":
            return api.session_recent(
                str(body.get("session_id") or ""),
                query=str(body.get("query") or ""),
                top_k=int(body.get("top_k", 10)),
                min_score=float(body.get("min_score", 0.3)),
            )
        if action == "search":
            return api.session_search_text(
                str(body.get("session_id") or ""),
                str(body.get("query") or ""),
                top_k=int(body.get("top_k", 10)),
                min_score=float(body.get("min_score", 0.3)),
            )
        if action == "latest-attachments":
            return api.session_latest_attachments(
                str(body.get("session_id") or ""),
                limit=int(body.get("limit", 10)),
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
        if rest == ["resources", "register"]:
            return sandbox.mutate(
                lambda: sandbox.resource_registry.register_resource(
                    str(body.get("resource_id") or ""),
                    str(body.get("root") or ""),
                    resource_type=str(body.get("resource_type") or "context_tree"),
                    config_path=str(body.get("config_path") or ""),
                    maintain_interval_sec=body.get("maintain_interval_sec"),
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
        if len(parts) == 2 and parts[0] == "identity":
            return self._dispatch_identity_brain(sandbox, parts[1], body)
        if len(parts) == 2 and parts[0] == "session":
            return self._dispatch_session_brain(sandbox, parts[1], body)
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
