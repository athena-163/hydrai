import json
import os
import tempfile
import unittest
from unittest import mock

from hydrai_memory.identity_state import IdentityState


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


def _make_identity(tmpdir: str, **kwargs) -> IdentityState:
    identity = IdentityState.create(tmpdir, **kwargs)
    if identity.llm is not None:
        identity.llm.summarize = mock.MagicMock(side_effect=lambda content, prompt, **kw: f"Summary of {content[:30]}")
    return identity


class IdentityStateTests(unittest.TestCase):
    def test_create_scaffolds_directories_and_identity_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp)
            for d in IdentityState.DIRS:
                self.assertTrue(os.path.isdir(os.path.join(ident.root, d)))
            self.assertTrue(os.path.isfile(os.path.join(ident.root, "identity", "SOUL.md")))
            self.assertTrue(os.path.isfile(os.path.join(ident.root, "identity", "PERSONA.md")))

    def test_create_with_config_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp, config={"model": "grok"})
            self.assertEqual(ident.config()["model"], "grok")

    def test_soul_and_persona_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp)
            ident.set_soul("Inner truth.")
            ident.set_persona("Helpful outward role.")
            self.assertEqual(ident.soul(), "Inner truth.")
            self.assertEqual(ident.persona(), "Helpful outward role.")

    def test_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp)
            ident.set_config({"skills": {"blacklist": ["email"]}})
            self.assertEqual(ident.config()["skills"]["blacklist"], ["email"])

    def test_dynamic_and_self_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp)
            ident.set_dynamic("self", "Self-reflection.")
            ident.set_dynamic("zeus", "Creator.")
            self.assertEqual(ident.dynamic("self"), "Self-reflection.")
            self.assertEqual(ident.get_friends(), ["zeus"])

    def test_ongoing_uses_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp)
            ident.set_ongoing("session-1", "Continuity note.")
            self.assertEqual(ident.ongoing("session-1"), "Continuity note.")
            self.assertEqual(ident.get_sessions(), ["session-1"])

    def test_add_memorable_slugifies_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp)
            filename = ident.add_memorable("First Lesson!", "Learned something.")
            self.assertEqual(filename, "0001.first-lesson.md")
            self.assertEqual(ident.memorable(filename), "Learned something.")

    def test_query_requires_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp)
            with self.assertRaises(ValueError):
                ident.query()

    def test_query_with_text_returns_results_and_ongoing(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp, embedder=_FakeEmbedder())
            ident.set_soul("I am Athena.")
            ident.set_persona("Helpful AI.")
            ident.set_dynamic("zeus", "Creator who values brevity")
            ident.set_ongoing("s1", "Working on Act 3.")
            ident.sync()
            result = ident.query(session_id="s1", query_text="creator", top_k=5)
            self.assertEqual(result["soul"], "I am Athena.")
            self.assertEqual(result["persona"], "Helpful AI.")
            self.assertEqual(result["ongoing"], "Working on Act 3.")
            self.assertIn("results", result)
            self.assertIsInstance(result["results"], list)

    def test_query_embed_wins_when_both_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            embedder = _FakeEmbedder()
            ident = _make_identity(tmp, embedder=embedder)
            ident.set_dynamic("zeus", "Creator who values brevity")
            ident.sync()
            result = ident.query(query_embed=embedder.embed("creator"), query_text="ignored", top_k=5)
            self.assertIn("results", result)

    def test_query_view_excludes_config_and_impulses(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp, embedder=_FakeEmbedder())
            ident.set_dynamic("zeus", "Creator")
            ident.sync()
            result = ident.query(query_text="creator")
            paths = [item["path"] for item in result["view"]]
            self.assertNotIn("config.json", paths)
            self.assertNotIn("impulses", paths)
            self.assertNotIn("impulses/", paths)

    def test_evolve_adds_and_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp, embedder=_FakeEmbedder())
            result = ident.evolve(
                new_memorables=[{"title": "Day 1", "content": "Good day."}],
                update_dynamics=[{"name": "self", "content": "Feeling focused."}],
                update_ongoing=[{"session_id": "chat", "content": "Casual tone."}],
            )
            self.assertEqual(
                result,
                {
                    "ok": True,
                    "memorables_added": 1,
                    "dynamics_updated": 1,
                    "ongoing_updated": 1,
                },
            )

    def test_evolve_update_ongoing_requires_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp)
            with self.assertRaises(ValueError):
                ident.evolve(update_ongoing=[{"session": "chat", "content": "bad shape"}])

    def test_invalid_tokens_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident = _make_identity(tmp)
            with self.assertRaises(ValueError):
                ident.set_dynamic("a/b", "x")
            with self.assertRaises(ValueError):
                ident.set_ongoing("../bad", "x")


if __name__ == "__main__":
    unittest.main()
