import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hydrai_memory.contexttree.auth import build_internal_auth_headers
from hydrai_memory.contexttree.core import ContexTree
from hydrai_memory.contexttree.prompt_config import load_summary_config, resolve_local_prompt_overrides
from hydrai_memory.contexttree.summary import load_summary


class _FakeEmbedder:
    def embed(self, text: str) -> str:
        text = (text or "")[:4].ljust(4, "_")
        raw = bytes(ord(ch) % 10 for ch in text)
        return raw.hex()

    def decode(self, vec_b64: str):
        return [float(b) for b in bytes.fromhex(vec_b64)]

    def similarity(self, vec_a, vec_b) -> float:
        if not vec_a or not vec_b:
            return 0.0
        total = sum(min(a, b) for a, b in zip(vec_a, vec_b))
        norm = max(sum(vec_a), sum(vec_b), 1.0)
        return total / norm


class PromptConfigTests(unittest.TestCase):
    def test_load_summary_config_reads_intelligence_ports_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contextree.json"
            path.write_text(
                json.dumps(
                    {
                        "intelligence": {
                            "base_url": "http://127.0.0.1",
                            "text_port": 61201,
                            "image_port": 61101,
                            "video_port": 61201,
                            "embedder_port": 61100,
                        },
                        "limits": {
                            "text_max_bytes": 1024,
                            "image_max_bytes": 2048,
                            "video_max_bytes": 4096,
                        },
                        "prompts": {"image_summary": "Focus on diagrams."},
                    }
                ),
                encoding="utf-8",
            )
            cfg = load_summary_config(str(path))
            self.assertEqual(cfg.intelligence_base_url, "http://127.0.0.1")
            self.assertEqual(cfg.embedder_port, 61100)
            self.assertEqual(cfg.text_max_bytes, 1024)
            self.assertEqual(cfg.image_max_bytes, 2048)
            self.assertEqual(cfg.video_max_bytes, 4096)
            self.assertEqual(cfg.prompts["image_summary"], "Focus on diagrams.")

    def test_load_summary_config_accepts_memory_json_context_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Memory.json"
            path.write_text(
                json.dumps(
                    {
                        "storage_root": "/tmp/hydrai",
                        "control_port": 62000,
                        "context_defaults": {
                            "intelligence": {
                                "base_url": "http://127.0.0.1",
                                "text_port": 61102,
                                "image_port": 61101,
                                "video_port": 61201,
                                "embedder_port": 61100,
                            },
                            "limits": {
                                "text_max_bytes": 2048,
                                "image_max_bytes": 4096,
                                "video_max_bytes": 8192,
                            },
                        },
                        "sandboxes": [
                            {
                                "id": "alpha",
                                "port": 62001,
                                "sandbox_space_root": "/Users/olympus",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            cfg = load_summary_config(str(path))
            self.assertEqual(cfg.text_port, 61102)
            self.assertEqual(cfg.image_port, 61101)
            self.assertEqual(cfg.video_port, 61201)
            self.assertEqual(cfg.embedder_port, 61100)
            self.assertEqual(cfg.text_max_bytes, 2048)

    def test_local_prompt_overrides_merge_parent_then_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            nested = root / "docs" / "images"
            nested.mkdir(parents=True)
            (root / ".PROMPT.json").write_text(
                json.dumps({"prompts": {"text_summary": "root text"}, "ports": {"text": 61201}}),
                encoding="utf-8",
            )
            ((root / "docs") / ".PROMPT.json").write_text(
                json.dumps(
                    {
                        "prompts": {"image_summary": "docs image"},
                        "ports": {"image": 61101},
                        "limits": {"image_max_bytes": 2048},
                    }
                ),
                encoding="utf-8",
            )
            (nested / ".PROMPT.json").write_text(
                json.dumps(
                    {
                        "prompts": {"image_summary": "nested image"},
                        "ports": {"embedder": 61100},
                        "limits": {"video_max_bytes": 8192},
                    }
                ),
                encoding="utf-8",
            )
            resolved = resolve_local_prompt_overrides(str(root), str(nested))
            self.assertEqual(resolved["prompts"]["text_summary"], "root text")
            self.assertEqual(resolved["prompts"]["image_summary"], "nested image")
            self.assertEqual(resolved["ports"]["text"], 61201)
            self.assertEqual(resolved["ports"]["image"], 61101)
            self.assertEqual(resolved["ports"]["embedder"], 61100)
            self.assertEqual(resolved["limits"]["image_max_bytes"], 2048)
            self.assertEqual(resolved["limits"]["video_max_bytes"], 8192)


class AuthTests(unittest.TestCase):
    def test_secure_mode_uses_route_specific_token(self):
        with mock.patch.dict(
            os.environ,
            {
                "HYDRAI_SECURITY_MODE": "secure",
                "HYDRAI_INTELLIGENCE_ROUTE_TOKENS_JSON": json.dumps(
                    {"61102": {"token_id": "mem-text", "token": "secret-text"}}
                ),
            },
            clear=False,
        ):
            headers = build_internal_auth_headers(61102)
            self.assertEqual(headers["X-Hydrai-Token-Id"], "mem-text")
            self.assertEqual(headers["X-Hydrai-Token"], "secret-text")

    def test_secure_mode_rejects_missing_route_specific_token(self):
        with mock.patch.dict(
            os.environ,
            {
                "HYDRAI_SECURITY_MODE": "secure",
                "HYDRAI_INTELLIGENCE_ROUTE_TOKENS_JSON": json.dumps(
                    {"61101": {"token_id": "mem-image", "token": "secret-image"}}
                ),
            },
            clear=False,
        ):
            with self.assertRaises(ValueError):
                build_internal_auth_headers(61102)


class ContexTreeTests(unittest.TestCase):
    def test_config_builds_embedder_and_limit_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            config_path = root / "contextree.json"
            config_path.write_text(
                json.dumps(
                    {
                        "intelligence": {
                            "base_url": "http://127.0.0.1",
                            "text_port": 61201,
                            "image_port": 61101,
                            "video_port": 61201,
                            "embedder_port": 61100,
                        },
                        "limits": {
                            "text_max_bytes": 123,
                            "image_max_bytes": 456,
                            "video_max_bytes": 789,
                        },
                    }
                ),
                encoding="utf-8",
            )
            tree = ContexTree(str(root), config_path=str(config_path))
            self.assertIsNotNone(tree.embedder)
            self.assertEqual(tree.text_max_bytes, 123)
            self.assertEqual(tree.image_max_bytes, 456)
            self.assertEqual(tree.video_max_bytes, 789)

    def test_oversized_image_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            image_path = root / "a.jpg"
            image_path.write_bytes(b"\xff\xd8" + b"x" * 20)
            tree = ContexTree(str(root), image_max_bytes=4)
            self.assertFalse(tree._within_media_limit(str(image_path), "image"))

    def test_local_limit_override_is_used_for_read_and_media_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            nested = root / "docs"
            nested.mkdir(parents=True)
            config_path = root / "contextree.json"
            config_path.write_text(
                json.dumps(
                    {
                        "intelligence": {
                            "base_url": "http://127.0.0.1",
                            "text_port": 61201,
                            "image_port": 61101,
                            "video_port": 61201,
                            "embedder_port": 61100,
                        },
                        "limits": {
                            "text_max_bytes": 100,
                            "image_max_bytes": 100,
                            "video_max_bytes": 100,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (nested / ".PROMPT.json").write_text(
                json.dumps(
                    {
                        "limits": {
                            "text_max_bytes": 5,
                            "image_max_bytes": 50,
                        }
                    }
                ),
                encoding="utf-8",
            )
            text_path = nested / "a.txt"
            text_path.write_text("0123456789", encoding="utf-8")
            image_path = nested / "a.jpg"
            image_path.write_bytes(b"\xff\xd8" + b"x" * 60)
            tree = ContexTree(str(root), config_path=str(config_path))
            read_result = tree.read(["docs/a.txt"])["docs/a.txt"]
            self.assertIn("... 5 more bytes", str(read_result))
            policy = tree._resolve_summary_policy(str(nested))
            self.assertFalse(tree._within_media_limit(str(image_path), "image", policy))

    def test_text_limit_is_byte_bounded_for_multibyte_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            config_path = root / "contextree.json"
            config_path.write_text(
                json.dumps(
                    {
                        "intelligence": {
                            "base_url": "http://127.0.0.1",
                            "text_port": 61201,
                            "image_port": 61101,
                            "video_port": 61201,
                            "embedder_port": 61100,
                        },
                        "limits": {"text_max_bytes": 4, "image_max_bytes": 100, "video_max_bytes": 100},
                    }
                ),
                encoding="utf-8",
            )
            text_path = root / "utf8.txt"
            text_path.write_text("你好世界", encoding="utf-8")
            tree = ContexTree(str(root), config_path=str(config_path))
            read_result = tree.read(["utf8.txt"])["utf8.txt"]
            self.assertEqual(str(read_result), "你\n... 8 more bytes")

    def test_write_text_auto_summarizes_when_summary_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            tree = ContexTree(str(root), embedder=_FakeEmbedder(), llm_url="http://unused")
            tree.llm.summarize_text = mock.Mock(return_value="auto summary")
            tree.write_text("notes/a.txt", "hello world")
            summary_data = load_summary(str(root / "notes"))
            self.assertEqual(summary_data["files"]["a.txt"]["text"], "auto summary")

    def test_copy_auto_summarizes_image_when_summary_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            src = Path(tmp) / "a.jpg"
            src.write_bytes(b"\xff\xd8" + b"x" * 20)
            tree = ContexTree(str(root), embedder=_FakeEmbedder(), vl_url="http://unused")
            tree.vl.summarize_image = mock.Mock(return_value="image summary")
            tree.copy("media/a.jpg", str(src))
            read_result = tree.read(["media/a.jpg"])["media/a.jpg"]
            self.assertEqual(read_result["summary"], "image summary")

    def test_maintenance_thread_starts_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            tree = ContexTree(str(root))
            calls = []

            def fake_sync(*args, **kwargs):
                calls.append((args, kwargs))
                time.sleep(0.05)
                return {"ok": True}

            tree.sync = fake_sync  # type: ignore[method-assign]
            tree.start_maintenance(interval=0.05)
            time.sleep(0.12)
            status = tree.maintenance_status()
            self.assertTrue(status["running"])
            tree.stop_maintenance(timeout=1)
            self.assertFalse(tree.maintenance_status()["running"])
            self.assertGreaterEqual(len(calls), 1)

    def test_write_read_and_view_text_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            tree = ContexTree(str(root), embedder=_FakeEmbedder())
            tree.write_text("notes/a.txt", "hello world", summary="greeting note")
            read_result = tree.read(["notes/a.txt"])
            self.assertIn("hello world", str(read_result["notes/a.txt"]))
            view_result = tree.view(depth=-1, summary_depth=1)
            paths = [item["path"] for item in view_result]
            self.assertIn("notes/", paths)
            self.assertIn("notes/a.txt", paths)

    def test_sync_generates_folder_and_file_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            (root / "a.txt").write_text("hello from file", encoding="utf-8")
            tree = ContexTree(str(root), llm_url="http://unused", llm_model="test", embedder=_FakeEmbedder())
            tree.llm.summarize_text = mock.Mock(return_value="file summary")
            tree.llm.summarize_folder = mock.Mock(return_value="folder summary")
            result = tree.sync()
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["files_summarized"], 1)
            folder_summary = tree.folder_summary("")
            self.assertEqual(folder_summary, "folder summary")
            view_result = tree.view(depth=1, summary_depth=1)
            file_item = next(item for item in view_result if item["path"] == "a.txt")
            self.assertEqual(file_item["summary"], "file summary")

    def test_search_by_text_returns_ranked_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            tree = ContexTree(str(root), embedder=_FakeEmbedder())
            tree.write_text("alpha.txt", "aaa", summary="alpha")
            tree.write_text("beta.txt", "bbb", summary="beta")
            results = tree.search_by_text("alpha", top_k=5, min_score=0.0)
            self.assertGreaterEqual(results["checked"], 2)
            self.assertTrue(any(item["path"] == "alpha.txt" for item in results["results"]))


if __name__ == "__main__":
    unittest.main()
