import os
import tempfile
import unittest
from pathlib import Path

from hydrai_memory.contexttree import ContexTree
from hydrai_memory.identity_state import IdentityStore
from hydrai_memory.resources import ResourceRegistry
from hydrai_memory.sessionbook import SessionBrainAPI, SessionStore


class _FakeEmbedder:
    def embed(self, text: str) -> str:
        if "diagram" in str(text).lower():
            return "AACAPw=="
        if "workspace" in str(text).lower():
            return "AABAQA=="
        return "AAAAPw=="

    def decode(self, vec_b64: str):
        import base64
        import numpy as np

        return np.frombuffer(base64.b64decode(vec_b64), dtype=np.float32)

    def similarity(self, vec_a, vec_b) -> float:
        import numpy as np

        if np.array_equal(vec_a, vec_b):
            return 1.0
        return 0.4


class SessionManagerTests(unittest.TestCase):
    def _make_layout(self, tmp: str) -> tuple[str, str]:
        storage_root = os.path.join(tmp, "memory")
        sandbox_root = os.path.join(storage_root, "sandboxes", "alpha")
        os.makedirs(os.path.join(sandbox_root, "sessions"), exist_ok=True)
        os.makedirs(os.path.join(sandbox_root, "identities"), exist_ok=True)
        os.makedirs(os.path.join(sandbox_root, "human"), exist_ok=True)
        os.makedirs(os.path.join(sandbox_root, "native"), exist_ok=True)
        return storage_root, sandbox_root

    def _seed_participants(self, storage_root: str) -> IdentityStore:
        store = IdentityStore(storage_root, "alpha", embedder=_FakeEmbedder())
        store.create_identity("athena", "Strategist", "Core self", {})
        store.create_human("zeus", "Project owner")
        native_root = os.path.join(storage_root, "sandboxes", "alpha", "native", "codex")
        os.makedirs(native_root, exist_ok=True)
        Path(native_root, "PERSONA.md").write_text("Coding copilot", encoding="utf-8")
        return store

    def test_create_list_and_delete_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root, sandbox_root = self._make_layout(tmp)
            self._seed_participants(storage_root)
            resource_root = os.path.join(tmp, "sandbox-home", "workspace")
            os.makedirs(resource_root, exist_ok=True)
            ResourceRegistry(sandbox_root).register_resource("workspace-main", resource_root)

            store = SessionStore(storage_root, "alpha", embedder=_FakeEmbedder())
            created = store.create_session(
                "athena-zeus",
                {"athena": "rw", "zeus": "ro", "codex": "ro"},
                {"workspace-main": "rw"},
                channel="telegram-1",
                brain={"route": "main"},
                limits={"recent_budget": 1024},
            )

            self.assertEqual(created["id"], "athena-zeus")
            self.assertEqual(created["identities"]["codex"], "ro")
            self.assertEqual(created["resources"]["workspace-main"], "rw")
            self.assertEqual(created["channel"], "telegram-1")
            self.assertEqual([item["id"] for item in store.list_sessions()], ["athena-zeus"])

            removed = store.delete_session("athena-zeus")
            self.assertEqual(removed["id"], "athena-zeus")
            self.assertEqual(store.list_sessions(), [])

    def test_session_store_does_not_leak_session_kwargs_into_identity_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root, sandbox_root = self._make_layout(tmp)
            self._seed_participants(storage_root)
            resource_root = os.path.join(tmp, "sandbox-home", "workspace")
            os.makedirs(resource_root, exist_ok=True)
            ResourceRegistry(sandbox_root).register_resource("workspace-main", resource_root)

            store = SessionStore(
                storage_root,
                "alpha",
                embedder=_FakeEmbedder(),
                max_chapter_bytes=2048,
                recent_budget=4096,
                context_budget=8192,
            )
            created = store.create_session("chat-1", {"athena": "rw"}, {"workspace-main": "rw"})

            self.assertEqual(created["id"], "chat-1")
            invited = store.invite_identity("chat-1", "zeus", "ro")
            self.assertEqual(invited["identities"]["zeus"], "ro")

    def test_invite_and_mount_validate_known_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root, sandbox_root = self._make_layout(tmp)
            self._seed_participants(storage_root)
            resource_root = os.path.join(tmp, "sandbox-home", "workspace")
            os.makedirs(resource_root, exist_ok=True)
            ResourceRegistry(sandbox_root).register_resource("workspace-main", resource_root)

            store = SessionStore(storage_root, "alpha", embedder=_FakeEmbedder())
            store.create_session("chat-1", {"athena": "rw"}, {})

            updated = store.invite_identity("chat-1", "codex", "ro")
            self.assertEqual(updated["identities"]["codex"], "ro")
            mounted = store.mount_resource("chat-1", "workspace-main", "ro")
            self.assertEqual(mounted["resources"]["workspace-main"], "ro")

            with self.assertRaises(FileNotFoundError):
                store.invite_identity("chat-1", "unknown", "rw")
            with self.assertRaises(FileNotFoundError):
                store.mount_resource("chat-1", "unknown", "rw")

    def test_attach_file_requires_sender_to_be_session_participant(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root, sandbox_root = self._make_layout(tmp)
            self._seed_participants(storage_root)
            ResourceRegistry(sandbox_root)
            store = SessionStore(storage_root, "alpha", embedder=_FakeEmbedder())
            store.create_session("chat-1", {"athena": "rw"}, {})

            src = Path(tmp) / "diagram.jpg"
            src.write_bytes(b"jpeg")

            with self.assertRaises(PermissionError):
                store.attach_file("chat-1", str(src), "codex", summary="diagram image")

            attached = store.attach_file("chat-1", str(src), "athena", summary="diagram image")
            self.assertEqual(attached["tag"], "0001.jpg")

    def test_session_recent_accepts_plain_text_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root, sandbox_root = self._make_layout(tmp)
            self._seed_participants(storage_root)
            ResourceRegistry(sandbox_root)
            store = SessionStore(storage_root, "alpha", embedder=_FakeEmbedder())
            store.create_session("chat-1", {"athena": "rw"}, {})
            book = store._load_session("chat-1")

            src = Path(tmp) / "diagram.jpg"
            src.write_bytes(b"jpeg")
            book.attach(str(src), "athena", summary="diagram sketch")
            book.append("latest turn")

            api = SessionBrainAPI(store)
            result = api.session_recent("chat-1", query="diagram", top_k=5, min_score=0.5)

            self.assertIn("latest turn", result["context"])
            self.assertIn("results", result)
            self.assertTrue(any(item["path"] == "attachments/0001.jpg" for item in result["results"]))

    def test_session_search_text_merges_session_and_resource_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root, sandbox_root = self._make_layout(tmp)
            self._seed_participants(storage_root)
            resource_root = os.path.join(tmp, "sandbox-home", "workspace")
            os.makedirs(resource_root, exist_ok=True)
            resource_tree = ContexTree(resource_root, embedder=_FakeEmbedder())
            resource_tree.write_text("notes.md", "workspace notes", summary="diagram workspace reference")
            ResourceRegistry(sandbox_root).register_resource("workspace-main", resource_root)

            store = SessionStore(storage_root, "alpha", embedder=_FakeEmbedder())
            store.create_session("chat-1", {"athena": "rw"}, {"workspace-main": "rw"})
            book = store._load_session("chat-1")
            src = Path(tmp) / "diagram.jpg"
            src.write_bytes(b"jpeg")
            book.attach(str(src), "athena", summary="diagram image")

            api = SessionBrainAPI(store)
            result = api.session_search_text("chat-1", "diagram", top_k=10, min_score=0.5)

            self.assertTrue(any(item["source_type"] == "session" and item["path"] == "attachments/0001.jpg" for item in result["results"]))
            self.assertTrue(any(item["source_type"] == "resource" and item["source_id"] == "workspace-main" and item["path"] == "notes.md" for item in result["results"]))
            scores = [float(item["score"]) for item in result["results"]]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_session_latest_attachments_returns_full_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root, sandbox_root = self._make_layout(tmp)
            self._seed_participants(storage_root)
            ResourceRegistry(sandbox_root)
            store = SessionStore(storage_root, "alpha", embedder=_FakeEmbedder())
            store.create_session("chat-1", {"athena": "rw"}, {})
            book = store._load_session("chat-1")

            for name in ("a.jpg", "b.png"):
                src = Path(tmp) / name
                src.write_bytes(b"data")
                book.attach(str(src), "athena", summary=f"summary for {name}")

            latest = SessionBrainAPI(store).session_latest_attachments("chat-1", limit=2)
            self.assertEqual([item["tag"] for item in latest], ["0002.png", "0001.jpg"])
            self.assertTrue(all(os.path.isabs(item["path"]) for item in latest))


if __name__ == "__main__":
    unittest.main()
