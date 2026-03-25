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

    def test_load_config_accepts_imap_smtp_backend(self):
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
            cfg = load_config(str(path))
            self.assertEqual(cfg.email.mailboxes[0].backend, "imap_smtp")
            self.assertEqual(cfg.email.imap_smtp["athena163"].imap_host, "imap.163.com")

    def test_load_config_accepts_gmail_oauth_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Toolbox.json"
            credentials = Path(tmp) / "google-client.json"
            token = Path(tmp) / "gmail-token.json"
            credentials.write_text("{}", encoding="utf-8")
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
                                    "address": "hydrai@gmail.com",
                                    "backend": "gmail_oauth",
                                    "backend_ref": "hydrai_gmail",
                                    "grants": [{"sandbox_id": "olympus", "identity_id": "athena", "mode": "rw"}],
                                }
                            ],
                            "backends": {
                                "himalaya": {"bin_name": "himalaya", "timeout_sec": 60},
                                "gmail_oauth": {
                                    "hydrai_gmail": {
                                        "email": "hydrai@gmail.com",
                                        "credentials_path": str(credentials),
                                        "token_path": str(token),
                                        "timeout_sec": 60,
                                        "scopes": [
                                            "https://www.googleapis.com/auth/gmail.readonly",
                                            "https://www.googleapis.com/auth/gmail.send"
                                        ]
                                    }
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            cfg = load_config(str(path))
            self.assertEqual(cfg.email.mailboxes[0].backend, "gmail_oauth")
            self.assertEqual(cfg.email.gmail_oauth["hydrai_gmail"].email, "hydrai@gmail.com")
