"""HTTP lifecycle for Toolbox."""

from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from hydrai_toolbox.auth import InternalAuthGate
from hydrai_toolbox.config import MailboxConfig, ServiceConfig
from hydrai_toolbox.providers import BraveWebSearchProvider, HimalayaEmailProvider

LOG = logging.getLogger("hydrai_toolbox.service")
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _manual_path() -> str:
    env_path = os.environ.get("HYDRAI_TOOLBOX_MANUAL_PATH", "").strip()
    if env_path:
        return os.path.realpath(os.path.expanduser(env_path))
    candidate = os.path.join(_PACKAGE_ROOT, "SPEC.md")
    if os.path.isfile(candidate):
        return candidate
    return ""


class ToolboxService:
    def __init__(self, config: ServiceConfig, auth_gate: InternalAuthGate):
        self._config = config
        self._auth_gate = auth_gate
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._email_send_locks: dict[str, threading.Lock] = {}

    def start(self) -> None:
        if self._server is not None:
            return
        self._server = self._make_server()
        self._thread = threading.Thread(target=self._server.serve_forever, name="hydrai-toolbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def wait(self) -> None:
        if self._thread is not None:
            self._thread.join()

    def _make_server(self) -> ThreadingHTTPServer:
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                service._handle_errors(self, lambda: service._dispatch_get(self))

            def do_POST(self) -> None:  # noqa: N802
                service._handle_errors(self, lambda: service._dispatch_post(self))

            def log_message(self, format: str, *args: Any) -> None:
                LOG.info("%s - %s", self.address_string(), format % args)

        return ThreadingHTTPServer(("127.0.0.1", self._config.control_port), Handler)

    def _require_auth(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._auth_gate.check(
            handler.headers.get("X-Hydrai-Token-Id"),
            handler.headers.get("X-Hydrai-Token"),
        ):
            raise HttpError(401, "unauthorized")

    def _read_json(self, handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        length_raw = handler.headers.get("Content-Length", "0") or "0"
        try:
            length = int(length_raw)
        except ValueError as exc:
            raise HttpError(400, "invalid content-length") from exc
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

    def _handle_errors(self, handler: BaseHTTPRequestHandler, fn: Callable[[], None]) -> None:
        try:
            fn()
        except json.JSONDecodeError:
            self._json(handler, 400, {"error": "invalid json"})
        except HttpError as exc:
            self._json(handler, exc.status, {"error": exc.message})
        except ValueError as exc:
            self._json(handler, 400, {"error": str(exc)})
        except FileNotFoundError:
            self._json(handler, 404, {"error": "not found"})
        except PermissionError as exc:
            self._json(handler, 403, {"error": str(exc)})
        except Exception as exc:
            LOG.exception("unhandled Toolbox service error")
            self._json(handler, 500, {"error": str(exc) or "internal server error"})

    def _help_payload(self) -> dict[str, Any]:
        return {
            "service": "Hydrai Toolbox",
            "security_mode": self._auth_gate.mode,
            "config_path": self._config.config_path,
            "control_port": self._server.server_address[1] if self._server else self._config.control_port,
            "manual_path": _manual_path(),
            "web_search_provider": self._config.web_search.provider,
            "mailboxes": [
                {
                    "address": mailbox.address,
                    "backend": mailbox.backend,
                    "display_name": mailbox.display_name,
                }
                for mailbox in self._config.email.mailboxes
            ],
            "endpoints": {
                "health": "GET /health",
                "help": "GET /help",
                "web_search": "POST /web/search",
                "email_search": "POST /email/search",
                "email_read": "POST /email/read",
                "email_send": "POST /email/send",
                "email_draft": "POST /email/draft",
            },
        }

    def _dispatch_get(self, handler: BaseHTTPRequestHandler) -> None:
        self._require_auth(handler)
        path = handler.path.split("?")[0]
        if path == "/health":
            self._json(handler, 200, {"status": "ok", "service": "toolbox", "port": self._server.server_address[1] if self._server else self._config.control_port})
            return
        if path == "/help":
            self._json(handler, 200, self._help_payload())
            return
        raise HttpError(404, "not found")

    def _dispatch_post(self, handler: BaseHTTPRequestHandler) -> None:
        self._require_auth(handler)
        body = self._read_json(handler)
        path = handler.path.split("?")[0]
        if path == "/web/search":
            self._json(handler, 200, self._web_search(body))
            return
        if path == "/email/search":
            self._json(handler, 200, self._email_search(body))
            return
        if path == "/email/read":
            self._json(handler, 200, self._email_read(body))
            return
        if path == "/email/send":
            self._json(handler, 200, self._email_send(body))
            return
        if path == "/email/draft":
            self._json(handler, 200, self._email_draft(body))
            return
        raise HttpError(404, "not found")

    def _web_search(self, body: dict[str, Any]) -> dict[str, Any]:
        query = str(body.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        count = int(body.get("count", 5))
        provider = BraveWebSearchProvider(
            api_key=os.environ.get(self._config.web_search.brave_key_env, "").strip(),
            timeout=self._config.web_search.brave_timeout_sec,
        )
        result = provider.search(query, count=count)
        if "error" in result:
            raise HttpError(502, str(result["error"]))
        return result

    def _lookup_mailbox(self, address: str) -> MailboxConfig:
        normalized = str(address or "").strip().lower()
        if not normalized:
            raise ValueError("address is required")
        for mailbox in self._config.email.mailboxes:
            if mailbox.address == normalized:
                return mailbox
        raise HttpError(404, f"unknown mailbox address: {normalized}")

    def _authorize_mailbox(self, mailbox: MailboxConfig, sandbox_id: str, identity_id: str, write: bool) -> None:
        sandbox = str(sandbox_id or "").strip()
        identity = str(identity_id or "").strip()
        if not sandbox:
            raise ValueError("sandbox_id is required")
        if not identity:
            raise ValueError("identity_id is required")
        for grant in mailbox.grants:
            if grant.sandbox_id == sandbox and grant.identity_id == identity:
                if write and grant.mode != "rw":
                    raise PermissionError("mailbox access denied: write requires rw grant")
                return
        raise PermissionError("mailbox access denied")

    def _email_provider(self, mailbox: MailboxConfig) -> HimalayaEmailProvider:
        if mailbox.backend != "himalaya":
            raise ValueError(f"unsupported email backend: {mailbox.backend}")
        return HimalayaEmailProvider(
            bin_name=self._config.email.himalaya.bin_name,
            timeout=self._config.email.himalaya.timeout_sec,
        )

    def _mailbox_lock(self, mailbox: MailboxConfig) -> threading.Lock:
        ref = mailbox.backend_ref
        if ref not in self._email_send_locks:
            self._email_send_locks[ref] = threading.Lock()
        return self._email_send_locks[ref]

    def _email_search(self, body: dict[str, Any]) -> dict[str, Any]:
        mailbox = self._lookup_mailbox(body.get("address"))
        self._authorize_mailbox(mailbox, body.get("sandbox_id", ""), body.get("identity_id", ""), write=False)
        provider = self._email_provider(mailbox)
        result = provider.search(
            query=str(body.get("query") or ""),
            limit=int(body.get("limit", 10)),
            account=mailbox.backend_ref,
            folder=str(body.get("folder") or ""),
        )
        if "error" in result:
            raise HttpError(502, str(result["error"]))
        return result

    def _email_read(self, body: dict[str, Any]) -> dict[str, Any]:
        mailbox = self._lookup_mailbox(body.get("address"))
        self._authorize_mailbox(mailbox, body.get("sandbox_id", ""), body.get("identity_id", ""), write=False)
        message_id = str(body.get("message_id") or "").strip()
        if not message_id:
            raise ValueError("message_id is required")
        provider = self._email_provider(mailbox)
        result = provider.read(message_id=message_id, account=mailbox.backend_ref)
        if "error" in result:
            raise HttpError(502, str(result["error"]))
        return result

    def _email_send(self, body: dict[str, Any]) -> dict[str, Any]:
        mailbox = self._lookup_mailbox(body.get("address"))
        self._authorize_mailbox(mailbox, body.get("sandbox_id", ""), body.get("identity_id", ""), write=True)
        provider = self._email_provider(mailbox)
        with self._mailbox_lock(mailbox):
            result = provider.send(
                to=_string_list(body.get("to")),
                cc=_string_list(body.get("cc")),
                bcc=_string_list(body.get("bcc")),
                subject=str(body.get("subject") or ""),
                body=str(body.get("body") or ""),
                account=mailbox.backend_ref,
            )
        if "error" in result:
            raise HttpError(502, str(result["error"]))
        return result

    def _email_draft(self, body: dict[str, Any]) -> dict[str, Any]:
        mailbox = self._lookup_mailbox(body.get("address"))
        self._authorize_mailbox(mailbox, body.get("sandbox_id", ""), body.get("identity_id", ""), write=True)
        provider = self._email_provider(mailbox)
        with self._mailbox_lock(mailbox):
            result = provider.draft(
                to=_string_list(body.get("to")),
                cc=_string_list(body.get("cc")),
                bcc=_string_list(body.get("bcc")),
                subject=str(body.get("subject") or ""),
                body=str(body.get("body") or ""),
                account=mailbox.backend_ref,
            )
        if "error" in result:
            raise HttpError(502, str(result["error"]))
        return result


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result
