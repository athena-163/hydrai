import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hydrai_memory.contexttree.summary import load_summary, save_summary, set_file_summary
from hydrai_memory.sessionbook import SessionBook


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


def _make_book(tmpdir: str, **kwargs) -> SessionBook:
    defaults = dict(
        root=tmpdir,
        llm_url="http://fake:9999",
        llm_model="test",
        max_chapter_bytes=100,
        min_break_bytes=20,
        recent_budget=200,
        context_budget=400,
    )
    defaults.update(kwargs)
    book = SessionBook(**defaults)
    book.llm.summarize = mock.MagicMock(side_effect=lambda content, prompt, **kw: f"Summary of {content[:30]}")
    return book


def _read_chapter(book: SessionBook, chapter: str) -> str:
    with open(os.path.join(book.root, chapter), "r", encoding="utf-8") as f:
        return f.read()


class SessionBookTests(unittest.TestCase):
    def test_default_config_uses_hydrai_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            self.assertEqual(
                book.config(),
                {
                    "channel": "",
                    "identities": {},
                    "resources": {},
                    "brain": {},
                    "attachments": {"next_serial": 1},
                    "limits": {},
                },
            )

    def test_create_with_hydrai_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = SessionBook.create(
                tmp,
                config={
                    "channel": "telegram-123",
                    "identities": {"zeus": "rw", "athena": "ro"},
                    "resources": {"workspace-main": "rw"},
                },
            )
            cfg = book.config()
            self.assertEqual(cfg["channel"], "telegram-123")
            self.assertEqual(cfg["identities"]["zeus"], "rw")
            self.assertEqual(cfg["resources"]["workspace-main"], "rw")

    def test_append_and_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp, max_chapter_bytes=50)
            book.append("A" * 60)
            book.append("fresh")
            self.assertIn("000001.log", book._list_chapters())
            self.assertEqual(_read_chapter(book, "000001.log"), "fresh\n")
            data = load_summary(book.root)
            self.assertTrue(data["files"]["000000.log"]["text"])

    def test_end_chapter_breaks_only_when_large_enough(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp, min_break_bytes=6)
            book.append("tiny")
            self.assertFalse(book.end_chapter())
            book.append(" and enough")
            self.assertTrue(book.end_chapter())

    def test_query_returns_identities_and_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            book.invite("athena", "rw")
            book.mount("workspace-main", "ro")
            book.append("hello")
            result = book.query()
            self.assertEqual(result["identities"], {"athena": "rw"})
            self.assertEqual(result["resources"], {"workspace-main": "ro"})

    def test_query_without_embed_omits_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            book.append("hello")
            result = book.query()
            self.assertNotIn("results", result)

    def test_query_uses_prior_summaries_and_recent_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp, min_break_bytes=5, max_chapter_bytes=10000, recent_budget=10, context_budget=400)
            book.append("A" * 60)
            book.end_chapter()
            book.append("recent text")
            result = book.query()
            self.assertIn("Summary of", result["context"])
            self.assertIn("recent text", result["context"])

    def test_attach_commits_file_and_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            src = Path(tmp) / "photo.jpg"
            src.write_bytes(b"\xff\xd8\xff\x00")
            tag = book.attach(str(src), "athena")
            self.assertEqual(tag, "0001.jpg")
            self.assertTrue(os.path.isfile(os.path.join(book.root, "attachments", tag)))
            self.assertEqual(_read_chapter(book, "000000.log"), f"[athena uploaded: {tag}]\n")

    def test_attach_manual_summary_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            src = Path(tmp) / "manual.jpg"
            src.write_bytes(b"\xff\xd8\xff\x00")
            tag = book.attach(str(src), "zeus", summary="whiteboard photo")
            info = book.attachment_info([tag])
            self.assertEqual(
                info,
                [{"tag": "0001.jpg", "path": os.path.join(book.root, "attachments", "0001.jpg"), "summary": "whiteboard photo"}],
            )

    def test_attachment_info_skips_missing_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            src = Path(tmp) / "manual.jpg"
            src.write_bytes(b"\xff\xd8\xff\x00")
            tag = book.attach(str(src), "zeus", summary="whiteboard photo")
            info = book.attachment_info([tag, "9999.jpg"])
            self.assertEqual(len(info), 1)
            self.assertEqual(info[0]["tag"], "0001.jpg")

    def test_attach_without_extension_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            src = Path(tmp) / "blob"
            src.write_bytes(b"data")
            with self.assertRaises(ValueError):
                book.attach(str(src), "athena")

    def test_latest_attachments_returns_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            for name in ("a.jpg", "b.png", "c.mp4"):
                src = Path(tmp) / name
                src.write_bytes(b"data")
                book.attach(str(src), "athena", summary=f"summary for {name}")
            latest = book.latest_attachments(limit=2)
            self.assertEqual([item["tag"] for item in latest], ["0003.mp4", "0002.png"])

    def test_recovery_deferred_to_write_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "000000.log"), "w", encoding="utf-8") as f:
                f.write("crashed chapter\n")
            with open(os.path.join(tmp, "000001.log"), "w", encoding="utf-8") as f:
                f.write("A" * 30 + "\n")
            book = _make_book(tmp, min_break_bytes=20)
            self.assertFalse(book.llm.summarize.called)
            book.end_chapter()
            data = load_summary(tmp)
            self.assertTrue(data["files"]["000000.log"]["text"])
            self.assertTrue(data["files"]["000001.log"]["text"])

    def test_config_limits_override_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as f:
                json.dump({"limits": {"max_chapter_bytes": 2048, "min_break_bytes": 64}}, f)
            book = SessionBook(tmp)
            self.assertEqual(book.max_chapter_bytes, 2048)
            self.assertEqual(book.min_break_bytes, 64)

    def test_proxy_text_backend_uses_tree_route_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "contextree.json"
            config.write_text(
                json.dumps(
                    {
                        "intelligence": {
                            "base_url": "http://127.0.0.1",
                            "text_port": 61102,
                            "image_port": 61101,
                            "video_port": 61201,
                            "embedder_port": 61100,
                        }
                    }
                ),
                encoding="utf-8",
            )
            book = SessionBook(tmp, config_path=str(config), min_break_bytes=5)
            book.llm.summarize = mock.MagicMock(side_effect=["chapter summary", "folder summary"])
            book.append("content for chapter")
            self.assertTrue(book.end_chapter())
            first = book.llm.summarize.call_args_list[0]
            self.assertEqual(first.kwargs["route_port"], 61102)
            self.assertEqual(first.kwargs["max_tokens"], 512)
            second = book.llm.summarize.call_args_list[1]
            self.assertEqual(second.kwargs["route_port"], 61102)
            self.assertEqual(second.kwargs["max_tokens"], 200)

    def test_invalid_identity_and_resource_ids_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            with self.assertRaises(ValueError):
                book.invite("", "rw")
            with self.assertRaises(ValueError):
                book.mount(" ", "rw")

    def test_search_with_query_embed_returns_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            embedder = _FakeEmbedder()
            book = _make_book(tmp, min_break_bytes=5, max_chapter_bytes=10000, embedder=embedder)
            book.append("discussion about authentication")
            book.end_chapter()
            book.append("active chapter")
            result = book.query(query_embed=embedder.embed("authentication"), top_k=5)
            self.assertIn("results", result)
            self.assertIsInstance(result["results"], list)

    def test_chapter_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            book.append("hello")
            info = book.chapter_info("000000.log")
            self.assertEqual(info["chapter"], "000000.log")
            self.assertFalse(info["closed"])

    def test_delegated_view_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _make_book(tmp)
            book.append("readable content")
            result = book.read(["000000.log"])
            self.assertIn("readable content", result["000000.log"])
            view = book.view()
            self.assertTrue(any(item["path"] == "000000.log" for item in view))


if __name__ == "__main__":
    unittest.main()
