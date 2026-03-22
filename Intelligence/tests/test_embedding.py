import unittest

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


if __name__ == "__main__":
    unittest.main()
