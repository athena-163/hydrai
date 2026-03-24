import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from hydrai_memory.auth import InternalAuthGate
from hydrai_memory.config import load_config
from hydrai_memory.service import MemoryService


def _request_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class MemoryServiceHttpTests(unittest.TestCase):
    def test_control_and_sandbox_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = os.path.join(tmp, "memory")
            sandbox_home = os.path.join(tmp, "sandbox-home")
            resource_root = os.path.join(sandbox_home, "workspace")
            os.makedirs(resource_root, exist_ok=True)
            config_path = os.path.join(tmp, "Memory.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "storage_root": storage_root,
                        "control_port": 0,
                        "sandboxes": [
                            {
                                "id": "alpha",
                                "port": 0,
                                "sandbox_space_root": sandbox_home,
                                "context_config_path": "",
                            }
                        ],
                    },
                    handle,
                    indent=2,
                )

            with mock.patch.dict(os.environ, {"HYDRAI_SECURITY_MODE": "dev"}, clear=False):
                service = MemoryService(load_config(config_path), InternalAuthGate.from_env())
                service.start()
                try:
                    control_port = service._control_server.server_address[1]
                    sandbox_port = service._sandboxes["alpha"].server.server_address[1]
                    control_base = f"http://127.0.0.1:{control_port}"
                    sandbox_base = f"http://127.0.0.1:{sandbox_port}"

                    help_payload = _request_json("GET", control_base + "/help")
                    self.assertEqual(help_payload["service"], "Hydrai Memory")
                    self.assertEqual(help_payload["sandboxes"][0]["id"], "alpha")

                    registered = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/resources/register",
                        {
                            "resource_id": "workspace-main",
                            "root": resource_root,
                        },
                    )
                    self.assertEqual(registered["id"], "workspace-main")

                    identity = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/identities/create",
                        {
                            "identity_id": "athena",
                            "persona": "Strategist",
                            "soul": "Core self",
                            "config": {},
                        },
                    )
                    self.assertEqual(identity["id"], "athena")

                    human = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/humans/create",
                        {
                            "identity_id": "zeus",
                            "persona": "Project owner",
                        },
                    )
                    self.assertEqual(human["id"], "zeus")

                    session = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/sessions/create",
                        {
                            "session_id": "chat-1",
                            "identities": {"athena": "rw", "zeus": "ro"},
                            "resources": {"workspace-main": "rw"},
                        },
                    )
                    self.assertEqual(session["id"], "chat-1")

                    wrote = _request_json(
                        "POST",
                        sandbox_base + "/tree/write",
                        {
                            "target_type": "resource",
                            "target_id": "workspace-main",
                            "path": "notes.md",
                            "content": "hello memory",
                            "summary": "workspace note",
                        },
                    )
                    self.assertTrue(wrote["ok"])

                    read_back = _request_json(
                        "POST",
                        sandbox_base + "/tree/read",
                        {
                            "target_type": "resource",
                            "target_id": "workspace-main",
                            "paths": ["notes.md"],
                        },
                    )
                    self.assertEqual(read_back["notes.md"], "hello memory")

                    profile = _request_json(
                        "POST",
                        sandbox_base + "/identity/profile",
                        {"identity_id": "athena"},
                    )
                    self.assertEqual(profile["persona"], "Strategist")
                    self.assertEqual(profile["soul"], "Core self")

                    attachment_path = os.path.join(tmp, "diagram.jpg")
                    Path(attachment_path).write_bytes(b"jpeg")
                    attached = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/sessions/chat-1/attach",
                        {
                            "source_path": attachment_path,
                            "sender": "athena",
                            "summary": "diagram image",
                        },
                    )
                    self.assertEqual(attached["tag"], "0001.jpg")

                    latest = _request_json(
                        "POST",
                        sandbox_base + "/session/latest-attachments",
                        {"session_id": "chat-1", "limit": 5},
                    )
                    self.assertEqual(latest[0]["tag"], "0001.jpg")

                    recent = _request_json(
                        "POST",
                        sandbox_base + "/session/recent",
                        {"session_id": "chat-1"},
                    )
                    self.assertEqual(recent["identities"]["athena"], "rw")
                    self.assertEqual(recent["resources"]["workspace-main"], "rw")

                    search = _request_json(
                        "POST",
                        sandbox_base + "/tree/search",
                        {
                            "target_type": "resource",
                            "target_id": "workspace-main",
                            "query_text": "workspace",
                        },
                    )
                    self.assertIn("results", search)

                    watchdog = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/resources/watchdog/start",
                        {"interval": 0.05},
                    )
                    self.assertTrue(watchdog["running"])
                finally:
                    service.stop()

    def test_secure_mode_rejects_missing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = os.path.join(tmp, "memory")
            sandbox_home = os.path.join(tmp, "sandbox-home")
            os.makedirs(sandbox_home, exist_ok=True)
            config_path = os.path.join(tmp, "Memory.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "storage_root": storage_root,
                        "control_port": 0,
                        "sandboxes": [
                            {
                                "id": "alpha",
                                "port": 0,
                                "sandbox_space_root": sandbox_home,
                                "context_config_path": "",
                            }
                        ],
                    },
                    handle,
                    indent=2,
                )

            with mock.patch.dict(
                os.environ,
                {
                    "HYDRAI_SECURITY_MODE": "secure",
                    "HYDRAI_INTERNAL_TOKENS_JSON": json.dumps({"memory": "secret"}),
                },
                clear=False,
            ):
                service = MemoryService(load_config(config_path), InternalAuthGate.from_env())
                service.start()
                try:
                    control_port = service._control_server.server_address[1]
                    req = urllib.request.Request(f"http://127.0.0.1:{control_port}/help", method="GET")
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(req, timeout=5)
                    self.assertEqual(ctx.exception.code, 401)
                    ctx.exception.close()
                finally:
                    service.stop()


if __name__ == "__main__":
    unittest.main()
