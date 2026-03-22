"""HTTP server lifecycle."""

from __future__ import annotations

import json
import logging
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
        self.server = ThreadingHTTPServer(("127.0.0.1", route.listen), self._make_handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name=f"route-{route.listen}")

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
        self.thread.start()
        LOG.info("started route %s on :%s", self.route.name, self.route.listen)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.adapter.shutdown()
        LOG.info("stopped route %s on :%s", self.route.name, self.route.listen)


class IntelligenceService:
    def __init__(self, config: ServiceConfig, auth_gate: InternalAuthGate):
        embedding_backend = EmbeddingBackend()
        self._runtimes = [RouteRuntime(route, auth_gate, embedding_backend) for route in config.routes]

    def start(self) -> None:
        started: list[RouteRuntime] = []
        try:
            for runtime in self._runtimes:
                runtime.start()
                started.append(runtime)
        except Exception:
            for runtime in reversed(started):
                runtime.stop()
            raise

    def wait(self) -> None:
        for runtime in self._runtimes:
            runtime.thread.join()

    def stop(self) -> None:
        for runtime in reversed(self._runtimes):
            runtime.stop()

