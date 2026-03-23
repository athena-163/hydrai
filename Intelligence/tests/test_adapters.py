import unittest
from unittest import mock

from intelligence.adapters import _resolve_llama_server_bin


class AdapterTests(unittest.TestCase):
    def test_resolve_llama_server_bin_uses_common_homebrew_path(self):
        with (
            mock.patch("intelligence.adapters.shutil.which", return_value=None),
            mock.patch("intelligence.adapters.os.path.isfile", side_effect=lambda path: path == "/opt/homebrew/bin/llama-server"),
            mock.patch("intelligence.adapters.os.access", return_value=True),
        ):
            self.assertEqual(_resolve_llama_server_bin(), "/opt/homebrew/bin/llama-server")


if __name__ == "__main__":
    unittest.main()
