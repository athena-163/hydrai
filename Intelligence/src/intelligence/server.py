"""HTTP server lifecycle."""

from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .adapters import (
    BadRequestError,
    IntelligenceError,
    UnsupportedFeatureError,
    UpstreamError,
    build_adapter,
)
from .auth import InternalAuthGate
from .concurrency import RouteBusyError, RouteLimiter
from .config import RouteConfig, ServiceConfig
from .embedding import EmbeddingBackend

LOG = logging.getLogger("intelligence.server")


class RouteRuntime:
    def __init__(self, route: RouteConfig, auth_gate: InternalAuthGate, embedding_backend: EmbeddingBackend):
        self.route = route
        self.auth_gate = auth_gate
        self.limiter = RouteLimiter(route.limits.max_concurrency)
        self.adapter = build_adapter(route, embedding_backend)
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def _make_handler(self):
        runtime = self

        class IntelligenceHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/health":
                    self._json(404, {"error": "not found"})
                    return
                if not runtime.auth_gate.check(
                    self.headers.get("X-Hydrai-Token-Id"),
                    self.headers.get("X-Hydrai-Token"),
                ):
                    self._json(401, {"error": "unauthorized"})
                    return
                payload = runtime.adapter.health()
                payload["port"] = runtime.route.listen
                payload["active_requests"] = runtime.limiter.active
                self._json(200, payload)

            def do_POST(self):
                if not runtime.auth_gate.check(
                    self.headers.get("X-Hydrai-Token-Id"),
                    self.headers.get("X-Hydrai-Token"),
                ):
                    self._json(401, {"error": "unauthorized"})
                    return
                try:
                    body = self._read_json()
                    with runtime.limiter.slot():
                        if self.path == "/v1/chat/completions":
                            if runtime.route.type != "chat":
                                self._json(404, {"error": "not found"})
                                return
                            status, payload = runtime.adapter.chat(body)
                            self._json(status, payload)
                            return
                        if self.path == "/v1/embeddings":
                            if runtime.route.type != "embedding":
                                self._json(404, {"error": "not found"})
                                return
                            status, payload = runtime.adapter.embeddings(body)
                            self._json(status, payload)
                            return
                        self._json(404, {"error": "not found"})
                except RouteBusyError:
                    self._json(503, {"error": "route busy"})
                except BadRequestError as exc:
                    self._json(400, {"error": str(exc)})
                except UnsupportedFeatureError as exc:
                    self._json(422, {"error": str(exc)})
                except UpstreamError as exc:
                    self._json(exc.status_code, exc.payload)
                except IntelligenceError as exc:
                    self._json(500, {"error": str(exc)})
                except json.JSONDecodeError:
                    self._json(400, {"error": "invalid json"})
                except ValueError:
                    self._json(400, {"error": "invalid content-length"})
                except Exception:
                    LOG.exception("unhandled route error on %s", runtime.route.name)
                    self._json(500, {"error": "internal server error"})

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length > 0 else b"{}"
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise BadRequestError("request body must be a JSON object")
                return data

            def _json(self, status: int, payload: Any):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args):
                LOG.info("[route:%s] " + fmt, runtime.route.listen, *args)

        return IntelligenceHandler

    def start(self) -> None:
        self.adapter.startup()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.route.listen), self._make_handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name=f"route-{self.route.listen}")
        self.thread.start()
        LOG.info("started route %s on :%s", self.route.name, self.route.listen)

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.thread = None
        self.adapter.shutdown()
        LOG.info("stopped route %s on :%s", self.route.name, self.route.listen)


class IntelligenceService:
    def __init__(self, config: ServiceConfig, auth_gate: InternalAuthGate):
        self._config = config
        self._auth_gate = auth_gate
        embedding_backend = EmbeddingBackend()
        self._runtimes = [RouteRuntime(route, auth_gate, embedding_backend) for route in config.routes]
        self._control_server: ThreadingHTTPServer | None = None
        self._control_thread: threading.Thread | None = None

    def _make_control_handler(self):
        service = self

        class ControlHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/health":
                    self._json(200, {"status": "ok", "service": "intelligence", "port": service._config.control_port})
                    return
                if self.path == "/help":
                    self._json(200, service._help_payload())
                    return
                self._json(404, {"error": "not found"})

            def _json(self, status: int, payload: Any):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args):
                LOG.info("[control:%s] " + fmt, service._config.control_port, *args)

        return ControlHandler

    def _help_payload(self) -> dict[str, Any]:
        return {
            "service": "Hydrai Intelligence",
            "control_port": self._config.control_port,
            "security_mode": self._auth_gate.mode,
            "config_path": self._config.config_path,
            "workspace_hint": os.path.expanduser("~/Public/hydrai"),
            "usage": {
                "startup": "hydrai-intelligence --config ~/Public/hydrai/Intelligence.json",
                "endpoints": {
                    "chat": "POST /v1/chat/completions",
                    "embeddings": "POST /v1/embeddings",
                    "route_health": "GET /health",
                    "service_help": "GET /help",
                    "service_health": "GET /health",
                },
            },
            "routes": [
                {
                    "name": runtime.route.name,
                    "type": runtime.route.type,
                    "adapter": runtime.route.adapter,
                    "listen": runtime.route.listen,
                    "model": runtime.route.model,
                    "search": runtime.route.search,
                    "think": list(runtime.route.think),
                    "modalities": runtime.route.modalities,
                    "context_k": runtime.route.context_k,
                    "max_concurrency": runtime.route.limits.max_concurrency,
                    "runtime_port": runtime.route.runtime_port if runtime.route.adapter == "llama" else 0,
                }
                for runtime in self._runtimes
            ],
        }

    def start(self) -> None:
        started: list[RouteRuntime] = []
        try:
            self._control_server = ThreadingHTTPServer(("127.0.0.1", self._config.control_port), self._make_control_handler())
            self._control_thread = threading.Thread(target=self._control_server.serve_forever, daemon=True, name="intelligence-control")
            self._control_thread.start()
            LOG.info("started Intelligence control server on :%s", self._config.control_port)
            for runtime in self._runtimes:
                runtime.start()
                started.append(runtime)
        except Exception:
            for runtime in reversed(self._runtimes):
                runtime.stop()
            if self._control_server is not None:
                self._control_server.shutdown()
                self._control_server.server_close()
                self._control_server = None
            self._control_thread = None
            raise

    def wait(self) -> None:
        if self._control_thread is not None:
            self._control_thread.join()
        for runtime in self._runtimes:
            if runtime.thread is not None:
                runtime.thread.join()

    def stop(self) -> None:
        for runtime in reversed(self._runtimes):
            runtime.stop()
        if self._control_server is not None:
            self._control_server.shutdown()
            self._control_server.server_close()
            self._control_server = None
            self._control_thread = None
            LOG.info("stopped Intelligence control server on :%s", self._config.control_port)
