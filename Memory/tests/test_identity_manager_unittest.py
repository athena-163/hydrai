import os
import tempfile
import unittest
from unittest import mock

from hydrai_memory.identity_state import IdentityBrainAPI, IdentityStore
from hydrai_memory.contexttree.summary import load_summary, save_summary, set_file_summary


class _FakeEmbedder:
    def embed(self, text: str) -> str:
        if "memory" in text.lower():
            return "AACAPw=="
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


class IdentityManagerTests(unittest.TestCase):
    def _make_store(self, tmp: str) -> IdentityStore:
        storage_root = os.path.join(tmp, "memory")
        os.makedirs(os.path.join(storage_root, "sandboxes", "alpha", "identities"), exist_ok=True)
        return IdentityStore(storage_root, "alpha", embedder=_FakeEmbedder())

    def test_create_list_get_delete_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            created = store.create_identity("athena", "Helpful strategist", "Private compass", {})
            self.assertEqual(created["id"], "athena")
            self.assertEqual(created["persona"], "Helpful strategist")
            self.assertEqual(created["soul"], "Private compass")

            self.assertEqual(store.get_identity("athena")["persona"], "Helpful strategist")
            self.assertEqual([item["id"] for item in store.list_identities()], ["athena"])

            removed = store.delete_identity("athena")
            self.assertEqual(removed["id"], "athena")
            self.assertIsNone(store.get_identity("athena"))

    def test_create_identity_requires_non_empty_persona_and_soul(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            with self.assertRaises(ValueError):
                store.create_identity("athena", "", "Private compass", {})
            with self.assertRaises(ValueError):
                store.create_identity("athena", "Helpful strategist", "", {})

    def test_setters_update_summary_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.create_identity("athena", "Helpful strategist", "Private compass", {})

            store.set_identity_persona("athena", "Battle planner")
            store.set_identity_soul("athena", "Inner law")
            store.set_identity_config("athena", {"skills": {"blacklist": ["email"]}})

            item = store.get_identity("athena")
            self.assertEqual(item["persona"], "Battle planner")
            self.assertEqual(item["soul"], "Inner law")
            self.assertEqual(item["config"]["skills"]["blacklist"], ["email"])

    def test_create_identity_rejects_duplicate_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.create_identity("athena", "Helpful strategist", "Private compass", {})
            with self.assertRaises(FileExistsError):
                store.create_identity("athena", "Other persona", "Other soul", {})

    def test_identity_profile_relations_sessions_and_memorables(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            athena = store.create_identity("athena", "Helpful strategist", "Private compass", {})
            store.create_identity("artemis", "Quiet scout", "Moon oath", {})
            api = IdentityBrainAPI(store)

            ident = store._load_identity("athena")
            if ident.llm is not None:
                ident.llm.summarize = mock.MagicMock(side_effect=lambda content, prompt, **kw: f"Summary of {content[:30]}")
            ident.set_dynamic("self", "Centered and watchful.")
            ident.set_dynamic("artemis", "Trusted hunter sister.")
            ident.set_ongoing("athena-artemis", "Shared pursuit remains active.")
            memorable_name = ident.add_memorable("Memory One", "Memory One full content.")
            second_memorable = ident.add_memorable("Memory Two", "Another memory full content.")
            ident.sync()
            memorables_root = os.path.join(ident.root, "memorables")
            data = load_summary(memorables_root)
            data = set_file_summary(data, memorable_name, "Memory One summary.", ident.embed("memory"))
            data = set_file_summary(data, second_memorable, "Memory Two summary.", ident.embed("memory"))
            save_summary(memorables_root, data)

            profile = api.identity_profile("athena")
            self.assertEqual(profile["persona"], athena["persona"])
            self.assertEqual(profile["soul"], athena["soul"])
            self.assertEqual(profile["self_dynamic"], "Centered and watchful.")
            self.assertEqual([item["id"] for item in profile["friends"]], ["artemis"])
            self.assertEqual([item["id"] for item in profile["sessions"]], ["athena-artemis"])
            self.assertEqual(profile["friends"][0]["summary"], "")
            self.assertEqual(profile["sessions"][0]["summary"], "")

            relations = api.identity_relations("athena", ["artemis", "missing"])
            self.assertEqual(relations["persona_map"]["artemis"], "Quiet scout")
            self.assertEqual(relations["dynamic_map"]["artemis"], "Trusted hunter sister.")
            self.assertNotIn("missing", relations["persona_map"])

            sessions = api.identity_sessions("athena", ["athena-artemis", "missing"])
            self.assertEqual(sessions["ongoing_map"], {"athena-artemis": "Shared pursuit remains active."})

            memorable = api.identity_memorables_search(
                "athena",
                "memory",
                top_content_n=1,
                top_summary_k=1,
                min_score=0.0,
            )
            self.assertEqual(len(memorable["best_contents"]), 1)
            self.assertIn("Memory One full content.", memorable["best_contents"][0]["content"])
            self.assertEqual(len(memorable["more_summaries"]), 1)
            self.assertTrue(memorable["more_summaries"][0]["summary"])


if __name__ == "__main__":
    unittest.main()
