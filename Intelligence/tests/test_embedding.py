import tempfile
import unittest
from pathlib import Path
from unittest import mock

from intelligence.embedding import EmbeddingBackend


class _FakeModel:
    def encode(self, _text, normalize_embeddings=True):
        return [1.0, 2.0, 3.0]


class EmbeddingTests(unittest.TestCase):
    def test_embedding_backend_base64_output(self):
        backend = EmbeddingBackend()
        backend._models["fake"] = _FakeModel()
        vector, dimension = backend.embed("fake", "hello")
        self.assertIsInstance(vector, str)
        self.assertEqual(dimension, 3)

    def test_embedding_backend_loads_models_from_local_cache_only(self):
        with mock.patch("intelligence.embedding.SentenceTransformer", return_value=_FakeModel()) as patched:
            backend = EmbeddingBackend()
            backend.embed("fake-model", "hello")
        patched.assert_called_once_with("fake-model", local_files_only=True)

    def test_embedding_backend_resolves_hf_snapshot_path(self):
        backend = EmbeddingBackend()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cache_root = home / ".cache" / "huggingface" / "hub" / "models--BAAI--bge-m3"
            snapshot = cache_root / "snapshots" / "rev123"
            snapshot.mkdir(parents=True)
            (cache_root / "refs").mkdir(parents=True)
            (cache_root / "refs" / "main").write_text("rev123")
            with mock.patch("intelligence.embedding.Path.home", return_value=home):
                resolved = backend._resolve_local_model_path("BAAI/bge-m3")
            self.assertEqual(resolved, str(snapshot))


if __name__ == "__main__":
    unittest.main()
