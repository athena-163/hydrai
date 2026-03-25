import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from hydrai_toolbox.auth import InternalAuthGate
from hydrai_toolbox.config import load_config
from hydrai_toolbox.service import ToolboxService


def _request_json(method: str, url: str, payload: dict | None = None, headers: dict | None = None) -> dict:
    data = None
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=req_headers)
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class ToolboxServiceTests(unittest.TestCase):
    def test_service_endpoints_and_mailbox_gating(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "Toolbox.json"
            config_path.write_text(
                json.dumps(
                    {
                        "control_port": 0,
                        "web_search": {
                            "provider": "brave",
                            "brave": {"key_env": "BRAVE_API_KEY", "timeout_sec": 15},
                        },
                        "email": {
                            "mailboxes": [
                                {
                                    "address": "athena@example.com",
                                    "backend": "himalaya",
                                    "backend_ref": "athena",
                                    "display_name": "Athena Mail",
                                    "grants": [
                                        {"sandbox_id": "olympus", "identity_id": "athena", "mode": "rw"},
                                        {"sandbox_id": "apollo", "identity_id": "athena", "mode": "ro"},
                                    ],
                                }
                            ],
                            "backends": {
                                "himalaya": {"bin_name": "himalaya", "timeout_sec": 60}
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(os.environ, {"HYDRAI_SECURITY_MODE": "dev", "BRAVE_API_KEY": "k"}, clear=False),
                mock.patch("hydrai_toolbox.service.BraveWebSearchProvider.search", return_value={"results": [{"title": "x", "url": "https://x", "description": "d"}]}),
                mock.patch("hydrai_toolbox.service.HimalayaEmailProvider.search", return_value={"messages": [{"id": "m1"}]}),
                mock.patch("hydrai_toolbox.service.HimalayaEmailProvider.read", return_value={"id": "m1", "body": "hello"}),
                mock.patch("hydrai_toolbox.service.HimalayaEmailProvider.send", return_value={"ok": True}),
                mock.patch("hydrai_toolbox.service.HimalayaEmailProvider.draft", return_value={"ok": True, "draft_id": "d1"}),
            ):
                service = ToolboxService(load_config(str(config_path)), InternalAuthGate.from_env())
                service.start()
                try:
                    port = service._server.server_address[1]
                    base = f"http://127.0.0.1:{port}"
                    help_payload = _request_json("GET", base + "/help")
                    self.assertEqual(help_payload["service"], "Hydrai Toolbox")
                    self.assertEqual(help_payload["mailboxes"][0]["address"], "athena@example.com")

                    search = _request_json("POST", base + "/web/search", {"query": "openai", "count": 3})
                    self.assertEqual(search["results"][0]["title"], "x")

                    email_search = _request_json(
                        "POST",
                        base + "/email/search",
                        {
                            "sandbox_id": "olympus",
                            "identity_id": "athena",
                            "address": "athena@example.com",
                            "query": "from:zeus",
                        },
                    )
                    self.assertEqual(email_search["messages"][0]["id"], "m1")

                    email_read = _request_json(
                        "POST",
                        base + "/email/read",
                        {
                            "sandbox_id": "apollo",
                            "identity_id": "athena",
                            "address": "athena@example.com",
                            "message_id": "m1",
                        },
                    )
                    self.assertEqual(email_read["body"], "hello")

                    send = _request_json(
                        "POST",
                        base + "/email/send",
                        {
                            "sandbox_id": "olympus",
                            "identity_id": "athena",
                            "address": "athena@example.com",
                            "to": ["zeus@example.com"],
                            "subject": "s",
                            "body": "b",
                        },
                    )
                    self.assertTrue(send["ok"])

                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        _request_json(
                            "POST",
                            base + "/email/send",
                            {
                                "sandbox_id": "apollo",
                                "identity_id": "athena",
                                "address": "athena@example.com",
                                "to": ["zeus@example.com"],
                                "subject": "s",
                                "body": "b",
                            },
                        )
                    self.assertEqual(ctx.exception.code, 403)
                    ctx.exception.close()
                finally:
                    service.stop()

    def test_secure_mode_rejects_missing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "Toolbox.json"
            config_path.write_text(
                json.dumps(
                    {
                        "control_port": 0,
                        "web_search": {
                            "provider": "brave",
                            "brave": {"key_env": "BRAVE_API_KEY", "timeout_sec": 15},
                        },
                        "email": {
                            "mailboxes": [
                                {
                                    "address": "athena@example.com",
                                    "backend": "himalaya",
                                    "backend_ref": "athena",
                                    "grants": [{"sandbox_id": "olympus", "identity_id": "athena", "mode": "rw"}],
                                }
                            ],
                            "backends": {
                                "himalaya": {"bin_name": "himalaya", "timeout_sec": 60}
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {"HYDRAI_SECURITY_MODE": "secure", "HYDRAI_INTERNAL_TOKENS_JSON": json.dumps({"toolbox": "secret"})},
                clear=False,
            ):
                service = ToolboxService(load_config(str(config_path)), InternalAuthGate.from_env())
                service.start()
                try:
                    port = service._server.server_address[1]
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/help", method="GET")
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(req, timeout=5)
                    self.assertEqual(ctx.exception.code, 401)
                    ctx.exception.close()
                finally:
                    service.stop()

    def test_service_supports_imap_smtp_mailbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "Toolbox.json"
            config_path.write_text(
                json.dumps(
                    {
                        "control_port": 0,
                        "web_search": {
                            "provider": "brave",
                            "brave": {"key_env": "BRAVE_API_KEY", "timeout_sec": 15},
                        },
                        "email": {
                            "mailboxes": [
                                {
                                    "address": "tokenian_athena@163.com",
                                    "backend": "imap_smtp",
                                    "backend_ref": "athena163",
                                    "grants": [{"sandbox_id": "olympus", "identity_id": "athena", "mode": "rw"}],
                                }
                            ],
                            "backends": {
                                "himalaya": {"bin_name": "himalaya", "timeout_sec": 60},
                                "imap_smtp": {
                                    "athena163": {
                                        "email": "tokenian_athena@163.com",
                                        "login": "tokenian_athena@163.com",
                                        "password_env": "tokenian_athena_163_com",
                                        "imap_host": "imap.163.com",
                                        "imap_port": 993,
                                        "imap_tls": True,
                                        "smtp_host": "smtp.163.com",
                                        "smtp_port": 465,
                                        "smtp_tls": True,
                                        "timeout_sec": 60,
                                        "inbox_folder": "INBOX",
                                        "sent_folder": "已发送",
                                        "drafts_folder": "草稿箱",
                                        "trash_folder": "已删除",
                                        "imap_id": {"name": "Hydrai Toolbox", "vendor": "Hydrai"},
                                    }
                                },
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(os.environ, {"HYDRAI_SECURITY_MODE": "dev"}, clear=False),
                mock.patch("hydrai_toolbox.service.ImapSmtpEmailProvider.search", return_value={"messages": [{"id": "7"}]}),
                mock.patch("hydrai_toolbox.service.ImapSmtpEmailProvider.read", return_value={"id": "7", "body": "hello", "folder": "INBOX"}),
            ):
                service = ToolboxService(load_config(str(config_path)), InternalAuthGate.from_env())
                service.start()
                try:
                    port = service._server.server_address[1]
                    base = f"http://127.0.0.1:{port}"
                    search = _request_json(
                        "POST",
                        base + "/email/search",
                        {
                            "sandbox_id": "olympus",
                            "identity_id": "athena",
                            "address": "tokenian_athena@163.com",
                            "query": "",
                            "limit": 3,
                        },
                    )
                    self.assertEqual(search["messages"][0]["id"], "7")
                    read = _request_json(
                        "POST",
                        base + "/email/read",
                        {
                            "sandbox_id": "olympus",
                            "identity_id": "athena",
                            "address": "tokenian_athena@163.com",
                            "message_id": "7",
                        },
                    )
                    self.assertEqual(read["body"], "hello")
                finally:
                    service.stop()
