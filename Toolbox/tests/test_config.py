import json
import tempfile
import unittest
from pathlib import Path

from hydrai_toolbox.config import load_config


class ToolboxConfigTests(unittest.TestCase):
    def test_load_config_accepts_valid_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Toolbox.json"
            path.write_text(
                json.dumps(
                    {
                        "control_port": 60000,
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
            cfg = load_config(str(path))
            self.assertEqual(cfg.control_port, 60000)
            self.assertEqual(cfg.web_search.provider, "brave")
            self.assertEqual(cfg.email.mailboxes[0].address, "athena@example.com")
            self.assertEqual(cfg.email.mailboxes[0].grants[1].sandbox_id, "apollo")

    def test_duplicate_mailbox_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Toolbox.json"
            path.write_text(
                json.dumps(
                    {
                        "control_port": 60000,
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
                                },
                                {
                                    "address": "athena@example.com",
                                    "backend": "himalaya",
                                    "backend_ref": "other",
                                    "grants": [{"sandbox_id": "olympus", "identity_id": "zeus", "mode": "ro"}],
                                },
                            ],
                            "backends": {
                                "himalaya": {"bin_name": "himalaya", "timeout_sec": 60}
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate mailbox address"):
                load_config(str(path))
