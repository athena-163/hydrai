import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hydrai_toolbox.providers import BraveWebSearchProvider, HimalayaEmailProvider


class ToolboxProviderTests(unittest.TestCase):
    def test_brave_search_success(self):
        provider = BraveWebSearchProvider(api_key="k")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"web": {"results": [{"title": "x", "url": "https://x", "description": "d"}]}}).encode("utf-8")

        with mock.patch("hydrai_toolbox.providers.urllib.request.urlopen", return_value=_Resp()):
            result = provider.search("hello", count=3)
        self.assertEqual(result["results"][0]["title"], "x")

    def test_himalaya_search_and_draft(self):
        provider = HimalayaEmailProvider(bin_name="himalaya")
        with mock.patch.object(provider, "_run", return_value=(0, '[{"id":"m1"}]', "")):
            result = provider.search("from:test", limit=5, account="athena")
        self.assertEqual(result["messages"][0]["id"], "m1")
        draft = provider.draft(["a@b.c"], "s", "b", account="athena")
        self.assertTrue(draft["ok"])
        self.assertTrue(Path(draft["path"]).is_file())
