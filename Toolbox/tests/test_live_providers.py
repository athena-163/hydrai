from __future__ import annotations

import os
import shutil
import time
import unittest

from hydrai_toolbox.providers import BraveWebSearchProvider, HimalayaEmailProvider, ImapSmtpEmailProvider


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

    def test_live_163_imap_search_and_read(self):
        password = os.environ.get("tokenian_athena_163_com", "").strip()
        if not password:
            self.skipTest("tokenian_athena_163_com is not set")
        provider = ImapSmtpEmailProvider(
            email="tokenian_athena@163.com",
            login="tokenian_athena@163.com",
            password_env="tokenian_athena_163_com",
            imap_host="imap.163.com",
            imap_port=993,
            imap_tls=True,
            smtp_host="smtp.163.com",
            smtp_port=465,
            smtp_tls=True,
            timeout=45,
            inbox_folder="INBOX",
            sent_folder="已发送",
            drafts_folder="草稿箱",
            trash_folder="已删除",
            imap_id={
                "name": "Hydrai Toolbox",
                "version": "0.1",
                "vendor": "Hydrai",
                "contact": "tokenian_athena@163.com",
            },
        )
        search = provider.search(query="", limit=3)
        self.assertNotIn("error", search)
        self.assertTrue(search.get("messages"))
        read = provider.read(search["messages"][0]["id"])
        self.assertNotIn("error", read)
        self.assertIn("Subject:", read["body"])
