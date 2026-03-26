import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
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
            archive_root = Path(tmp) / "archive-src" / "demo-skill"
            archive_root.mkdir(parents=True, exist_ok=True)
            (archive_root / "SKILL.md").write_text(
                "---\nname: demo-skill\ndescription: Installed demo skill.\n---\n\n# Demo\nUse this installed skill.\n",
                encoding="utf-8",
            )
            archive_path = Path(tmp) / "demo-skill.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for current_root, _dirnames, filenames in os.walk(archive_root.parent):
                    for filename in filenames:
                        full = Path(current_root) / filename
                        archive.write(full, full.relative_to(archive_root.parent))
            hub_index = Path(tmp) / "hub-index.json"
            hub_index.write_text(
                json.dumps(
                    {
                        "skills": [
                            {
                                "name": "demo-skill",
                                "summary": "Installed demo skill.",
                                "archive_url": archive_path.as_uri(),
                                "version": "1.0.0",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config_path = os.path.join(tmp, "Memory.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "storage_root": storage_root,
                        "control_port": 0,
                        "context_defaults": {
                            "intelligence": {
                                "base_url": "http://127.0.0.1",
                                "text_port": 61102,
                                "image_port": 61101,
                                "video_port": 61201,
                                "embedder_port": 61100
                            }
                        },
                        "trusted_skill_hubs": [
                            {
                                "id": "trusted",
                                "index_url": hub_index.as_uri(),
                                "site_url": "https://skills.example.test/",
                                "description": "Trusted test hub",
                            }
                        ],
                        "sandboxes": [
                            {
                                "id": "alpha",
                                "port": 0,
                                "sandbox_space_root": sandbox_home,
                                "skills": {
                                    "whitelist": ["context", "install_skill", "demo-skill"],
                                    "blacklist": []
                                }
                            }
                        ],
                    },
                    handle,
                    indent=2,
                )

            with (
                mock.patch.dict(os.environ, {"HYDRAI_SECURITY_MODE": "dev"}, clear=False),
                mock.patch("hydrai_memory.contexttree.embedder.Embedder.embed", return_value=""),
                mock.patch("hydrai_memory.contexttree.llm.LLMClient.summarize", return_value=""),
                mock.patch("hydrai_memory.contexttree.llm.VLClient.summarize_media", return_value=""),
            ):
                service = MemoryService(load_config(config_path), InternalAuthGate.from_env())
                service.start()
                try:
                    control_port = service._control_server.server_address[1]
                    sandbox_port = service._sandboxes["alpha"].server.server_address[1]
                    control_base = f"http://127.0.0.1:{control_port}"
                    sandbox_base = f"http://127.0.0.1:{sandbox_port}"

                    help_payload = _request_json("GET", control_base + "/help")
                    expected_config_path = os.path.realpath(config_path)
                    self.assertEqual(help_payload["service"], "Hydrai Memory")
                    self.assertEqual(help_payload["sandboxes"][0]["id"], "alpha")
                    self.assertIn("watchdog", help_payload["sandboxes"][0])
                    self.assertEqual(help_payload["sandboxes"][0]["context_defaults_source"], expected_config_path)
                    self.assertTrue(str(help_payload["manual_path"]).endswith("/hydrai_memory/MANUAL.md"))

                    sandbox_help = _request_json("GET", sandbox_base + "/help")
                    self.assertEqual(sandbox_help["context_defaults_source"], expected_config_path)
                    self.assertTrue(str(sandbox_help["manual_path"]).endswith("/hydrai_memory/MANUAL.md"))
                    self.assertIn("brain_bootstrap", sandbox_help["endpoints"])
                    self.assertNotIn("identity_profile", sandbox_help["endpoints"])

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

                    related_identity = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/identities/create",
                        {
                            "identity_id": "artemis",
                            "persona": "Scout",
                            "soul": "Field self",
                            "config": {},
                        },
                    )
                    self.assertEqual(related_identity["id"], "artemis")

                    blocked_identity = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/identities/create",
                        {
                            "identity_id": "hermes",
                            "persona": "Courier",
                            "soul": "Fast self",
                            "config": {"skills": {"blacklist": ["install_skill"]}},
                        },
                    )
                    self.assertEqual(blocked_identity["id"], "hermes")

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

                    wrote_identity_self = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/tree/write",
                        {
                            "target_type": "identity",
                            "target_id": "athena",
                            "path": "dynamics/self.md",
                            "content": "Keep the system coherent.",
                            "summary": "self guidance",
                        },
                    )
                    self.assertTrue(wrote_identity_self["ok"])

                    wrote_identity_friend = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/tree/write",
                        {
                            "target_type": "identity",
                            "target_id": "athena",
                            "path": "dynamics/artemis.md",
                            "content": "Trusted scout ally.",
                            "summary": "friend note",
                        },
                    )
                    self.assertTrue(wrote_identity_friend["ok"])

                    wrote_identity_ongoing = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/tree/write",
                        {
                            "target_type": "identity",
                            "target_id": "athena",
                            "path": "ongoing/chat-1.md",
                            "content": "Continue the design thread.",
                            "summary": "chat continuity",
                        },
                    )
                    self.assertTrue(wrote_identity_ongoing["ok"])

                    wrote = _request_json(
                        "POST",
                        sandbox_base + "/tree/write",
                        {
                            "target_type": "resource",
                            "target_id": "workspace-main",
                            "path": "notes.md",
                            "content": "hello memory",
                            "summary": "workspace note",
                            "actor_identity_id": "athena",
                            "session_id": "chat-1",
                        },
                    )
                    self.assertTrue(wrote["ok"])

                    with self.assertRaises(urllib.error.HTTPError) as denied_write:
                        _request_json(
                            "POST",
                            sandbox_base + "/tree/write",
                            {
                                "target_type": "resource",
                                "target_id": "workspace-main",
                                "path": "blocked.md",
                                "content": "should fail",
                                "actor_identity_id": "zeus",
                                "session_id": "chat-1",
                            },
                        )
                    self.assertEqual(denied_write.exception.code, 403)
                    denied_write.exception.close()

                    read_back = _request_json(
                        "POST",
                        sandbox_base + "/tree/read",
                        {
                            "target_type": "resource",
                            "target_id": "workspace-main",
                            "paths": ["notes.md"],
                            "actor_identity_id": "athena",
                            "session_id": "chat-1",
                        },
                    )
                    self.assertEqual(read_back["notes.md"], "hello memory")

                    bootstrap = _request_json(
                        "POST",
                        sandbox_base + "/brain/bootstrap",
                        {
                            "actor_identity_id": "athena",
                            "requestor_id": "zeus",
                            "session_id": "chat-1",
                            "query": "workspace design",
                            "attachment_limit": 3,
                        },
                    )
                    self.assertEqual(bootstrap["target_identity_id"], "athena")
                    self.assertEqual(bootstrap["requestor_persona"], "Project owner")
                    self.assertEqual(bootstrap["target_profile"]["persona"], "Strategist")
                    self.assertEqual(bootstrap["target_profile"]["soul"], "Core self")
                    self.assertEqual(bootstrap["target_profile"]["self_dynamic"], "Keep the system coherent.")
                    self.assertIn("artemis", bootstrap["friend_ids"])
                    self.assertIn("chat-1", bootstrap["session_ids"])
                    self.assertEqual(bootstrap["session"]["id"], "chat-1")
                    self.assertEqual(bootstrap["session"]["participants"]["athena"], "rw")
                    self.assertEqual(bootstrap["session"]["resources"]["workspace-main"], "rw")
                    self.assertEqual(bootstrap["session"]["mounted_resources"][0]["id"], "workspace-main")
                    self.assertEqual(bootstrap["session"]["latest_attachments"], [])
                    self.assertIn("results", bootstrap["session"]["search"])
                    self.assertTrue(any(item["name"] == "context" and item["prompt_text"] for item in bootstrap["skill_shortlist"]))

                    skill_sites = _request_json(
                        "POST",
                        sandbox_base + "/skills/trusted-sites",
                        {"actor_identity_id": "athena"},
                    )
                    self.assertEqual(skill_sites["results"][0]["id"], "trusted")

                    with self.assertRaises(urllib.error.HTTPError) as denied_sites:
                        _request_json(
                            "POST",
                            sandbox_base + "/skills/trusted-sites",
                            {"actor_identity_id": "hermes"},
                        )
                    self.assertEqual(denied_sites.exception.code, 403)
                    denied_sites.exception.close()

                    skill_listing = _request_json(
                        "POST",
                        sandbox_base + "/skills/list",
                        {"actor_identity_id": "athena"},
                    )
                    self.assertTrue(any(item["category"] == "shortlist" and item["name"] == "context" for item in skill_listing["results"]))

                    installed_skill = _request_json(
                        "POST",
                        sandbox_base + "/skills/install",
                        {
                            "actor_identity_id": "athena",
                            "hub_id": "trusted",
                            "skill_name": "demo-skill",
                        },
                    )
                    self.assertEqual(installed_skill["name"], "demo-skill")

                    skill_read = _request_json(
                        "POST",
                        sandbox_base + "/skills/read",
                        {
                            "actor_identity_id": "athena",
                            "name": "demo-skill",
                            "category": "user",
                        },
                    )
                    self.assertEqual(skill_read["results"][0]["category"], "user")

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
                        {"actor_identity_id": "athena", "session_id": "chat-1", "limit": 5},
                    )
                    self.assertEqual(latest[0]["tag"], "0001.jpg")

                    bootstrap_after_attachment = _request_json(
                        "POST",
                        sandbox_base + "/brain/bootstrap",
                        {
                            "actor_identity_id": "athena",
                            "requestor_id": "zeus",
                            "session_id": "chat-1",
                            "attachment_limit": 3,
                        },
                    )
                    self.assertEqual(bootstrap_after_attachment["session"]["latest_attachments"][0]["tag"], "0001.jpg")

                    recent = _request_json(
                        "POST",
                        sandbox_base + "/session/recent",
                        {"actor_identity_id": "athena", "session_id": "chat-1"},
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
                            "actor_identity_id": "athena",
                            "session_id": "chat-1",
                        },
                    )
                    self.assertIn("results", search)

                    accessible_resources = _request_json(
                        "POST",
                        sandbox_base + "/resources/list",
                        {"actor_identity_id": "athena", "session_id": "chat-1"},
                    )
                    resource_entries = [item for item in accessible_resources["results"] if item["target_type"] == "resource"]
                    session_entries = [item for item in accessible_resources["results"] if item["target_type"] == "session"]
                    identity_entries = [item for item in accessible_resources["results"] if item["target_type"] == "identity"]
                    self.assertEqual(identity_entries[0]["id"], "athena")
                    self.assertEqual(identity_entries[0]["mode"], "rw")
                    self.assertEqual(session_entries[0]["id"], "chat-1")
                    self.assertEqual(session_entries[0]["mode"], "rw")
                    self.assertEqual(resource_entries[0]["id"], "workspace-main")
                    self.assertEqual(resource_entries[0]["mode"], "rw")

                    bootstrap_without_session = _request_json(
                        "POST",
                        sandbox_base + "/brain/bootstrap",
                        {
                            "actor_identity_id": "athena",
                            "requestor_id": "zeus",
                        },
                    )
                    self.assertIsNone(bootstrap_without_session["session"])

                    with self.assertRaises(urllib.error.HTTPError) as bad_requestor:
                        _request_json(
                            "POST",
                            sandbox_base + "/brain/bootstrap",
                            {
                                "actor_identity_id": "athena",
                                "requestor_id": "missing-persona",
                            },
                        )
                    self.assertEqual(bad_requestor.exception.code, 404)
                    bad_requestor.exception.close()

                    watchdog = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/resources/watchdog/start",
                        {"interval": 0.05},
                    )
                    self.assertTrue(watchdog["running"])

                    watchdog_defaults = _request_json(
                        "POST",
                        control_base + "/sandboxes/alpha/resources/watchdog/defaults",
                        {"git_auto_commit_daily": True},
                    )
                    self.assertTrue(watchdog_defaults["default_git_auto_commit_daily"])
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
                        "context_defaults": {
                            "intelligence": {
                                "base_url": "http://127.0.0.1",
                                "text_port": 61102,
                                "image_port": 61101,
                                "video_port": 61201,
                                "embedder_port": 61100
                            }
                        },
                        "sandboxes": [
                            {
                                "id": "alpha",
                                "port": 0,
                                "sandbox_space_root": sandbox_home
                            }
                        ],
                    },
                    handle,
                    indent=2,
                )

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "HYDRAI_SECURITY_MODE": "secure",
                        "HYDRAI_INTERNAL_TOKENS_JSON": json.dumps({"memory": "secret"}),
                    },
                    clear=False,
                ),
                mock.patch("hydrai_memory.contexttree.embedder.Embedder.embed", return_value=""),
                mock.patch("hydrai_memory.contexttree.llm.LLMClient.summarize", return_value=""),
                mock.patch("hydrai_memory.contexttree.llm.VLClient.summarize_media", return_value=""),
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
