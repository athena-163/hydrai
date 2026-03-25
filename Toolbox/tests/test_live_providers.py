from __future__ import annotations

import os
import shutil
import time
import unittest

from hydrai_toolbox.providers import BraveWebSearchProvider, HimalayaEmailProvider


def _live_enabled() -> bool:
    return os.environ.get("HYDRAI_LIVE_TOOLBOX_TESTS", "").lower() in {"1", "true", "yes"}


@unittest.skipUnless(_live_enabled(), "set HYDRAI_LIVE_TOOLBOX_TESTS=1 to run live Toolbox provider tests")
class ToolboxLiveProviderTests(unittest.TestCase):
    def test_live_brave_search(self):
        api_key = os.environ.get("BRAVE_API_KEY", "").strip()
        if not api_key:
            self.skipTest("BRAVE_API_KEY is not set")
        provider = BraveWebSearchProvider(api_key=api_key, timeout=20)
        result = provider.search("OpenAI", count=3)
        self.assertNotIn("error", result)
        self.assertTrue(result.get("results"))

    def test_live_himalaya_search_and_send(self):
        bin_name = os.environ.get("HIMALAYA_BIN", "himalaya")
        if not shutil.which(bin_name):
            self.skipTest(f"himalaya binary not found: {bin_name}")
        account = os.environ.get("HYDRAI_TEST_EMAIL_ACCOUNT", "").strip()
        if not account:
            self.skipTest("HYDRAI_TEST_EMAIL_ACCOUNT is not set")
        provider = HimalayaEmailProvider(bin_name=bin_name, timeout=45)
        search = provider.search(query="", limit=3, account=account)
        self.assertNotIn("error", search)

        recipient = os.environ.get("HYDRAI_TEST_EMAIL_TO", "").strip()
        if not recipient:
            self.skipTest("HYDRAI_TEST_EMAIL_TO is not set")
        subject = f"[hydrai-toolbox-live-test] {int(time.time())}"
        send = provider.send(
            to=[recipient],
            subject=subject,
            body="Hydrai Toolbox live email send verification.",
            account=account,
        )
        self.assertNotIn("error", send)
        self.assertTrue(send.get("ok"))
