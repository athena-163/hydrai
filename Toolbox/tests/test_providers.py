import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hydrai_toolbox.providers import BraveWebSearchProvider, GmailOAuthEmailProvider, HimalayaEmailProvider


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

    def test_himalaya_send_treats_sent_copy_append_failure_as_warning(self):
        provider = HimalayaEmailProvider(bin_name="himalaya")
        stderr = "cannot add IMAP message: unexpected NO response: Folder not exist"
        with mock.patch.object(provider, "_run", return_value=(1, "", stderr)):
            result = provider.send(["a@b.c"], "s", "b", account="athena")
        self.assertTrue(result["ok"])
        self.assertIn("Folder not exist", result["warning"])

    def test_gmail_oauth_search_read_send_and_draft(self):
        provider = GmailOAuthEmailProvider(
            email="hydrai@gmail.com",
            credentials_path="/tmp/client.json",
            token_path="/tmp/token.json",
            scopes=("scope.read", "scope.send"),
        )

        class _Messages:
            def list(self, **kwargs):
                self.last_list = kwargs
                return self
            def get(self, **kwargs):
                self.last_get = kwargs
                return self
            def send(self, **kwargs):
                self.last_send = kwargs
                return self
            def execute(self):
                if getattr(self, "last_list", None):
                    return {"messages": [{"id": "m1"}]}
                if getattr(self, "last_get", None):
                    if self.last_get.get("format") == "metadata":
                        return {"payload": {"headers": [
                            {"name": "Subject", "value": "s"},
                            {"name": "From", "value": "a@example.com"},
                            {"name": "To", "value": "b@example.com"},
                            {"name": "Date", "value": "now"},
                        ]}}
                    return {"raw": "U3ViamVjdDogcw0KDQpoZWxsbw=="}
                return {"id": "x1"}

        class _Drafts:
            def create(self, **kwargs):
                self.last_create = kwargs
                return self
            def execute(self):
                return {"id": "d1"}

        class _Users:
            def __init__(self):
                self.messages_api = _Messages()
                self.drafts_api = _Drafts()
            def messages(self):
                return self.messages_api
            def drafts(self):
                return self.drafts_api

        class _Service:
            def users(self):
                return _Users()

        with mock.patch.object(provider, "_service", return_value=_Service()):
            search = provider.search("from:test", limit=2)
            self.assertEqual(search["messages"][0]["id"], "m1")
            read = provider.read("m1")
            self.assertIn("hello", read["body"])
            send = provider.send(["a@b.c"], "s", "body")
            self.assertTrue(send["ok"])
            draft = provider.draft(["a@b.c"], "s", "body")
            self.assertTrue(draft["ok"])
