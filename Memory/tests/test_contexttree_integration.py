import json
import os
import tempfile
import unittest

from hydrai_memory.contexttree.core import ContexTree


_RUN_REAL = os.environ.get("HYDRAI_RUN_REAL_INTELLIGENCE_TESTS", "").strip() == "1"
_DATA_ROOT = os.path.expanduser(os.environ.get("HYDRAI_CONTEXTREE_FIXTURE_ROOT", "~/Database/contextree"))


@unittest.skipUnless(_RUN_REAL, "set HYDRAI_RUN_REAL_INTELLIGENCE_TESTS=1 to run real Intelligence integration tests")
class ContexTreeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(_DATA_ROOT):
            raise unittest.SkipTest(f"fixture root not found: {_DATA_ROOT}")
        fd, cls._config_path = tempfile.mkstemp(prefix="hydrai-memory-real-", suffix=".json")
        os.close(fd)
        with open(cls._config_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "intelligence": {
                        "base_url": "http://127.0.0.1",
                        "text_port": 61102,
                        "image_port": 61101,
                        "video_port": 61201,
                        "embedder_port": 61100,
                    },
                    "limits": {
                        "text_max_bytes": 65536,
                        "image_max_bytes": 1024 * 1024,
                        "video_max_bytes": 10 * 1024 * 1024,
                    },
                },
                f,
            )
        cls.tree = ContexTree(_DATA_ROOT, config_path=cls._config_path)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_config_path", None) and os.path.exists(cls._config_path):
            os.unlink(cls._config_path)

    def test_live_text_summary_uses_qwen3_4b_route(self):
        doc_dir = os.path.join(_DATA_ROOT, "docs")
        summary = self.tree._summarize_text_file(
            os.path.join(doc_dir, "api_design.txt"),
            self.tree._resolve_summary_policy(doc_dir),
        )
        self.assertTrue(summary.strip())

    def test_live_image_summary_uses_qwen3_32b_vl_route(self):
        media_dir = os.path.join(_DATA_ROOT, "docs", "media")
        summary = self.tree._summarize_media_file(
            os.path.join(media_dir, "#cdl.Asian.@25.Happy.Side.1746706534698.jpg"),
            "image",
            self.tree._resolve_summary_policy(media_dir),
        )
        self.assertTrue(summary.strip())

    def test_live_video_summary_uses_qwen35_plus_route(self):
        media_dir = os.path.join(_DATA_ROOT, "docs", "media")
        summary = self.tree._summarize_media_file(
            os.path.join(media_dir, "1.mp4"),
            "video",
            self.tree._resolve_summary_policy(media_dir),
        )
        self.assertTrue(summary.strip())


if __name__ == "__main__":
    unittest.main()
