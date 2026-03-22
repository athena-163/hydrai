import os
import unittest

from intelligence.auth import AuthError, InternalAuthGate


class AuthTests(unittest.TestCase):
    def test_dev_mode_allows_requests(self):
        old = dict(os.environ)
        try:
            os.environ.pop("HYDRAI_INTERNAL_TOKENS_JSON", None)
            os.environ["HYDRAI_SECURITY_MODE"] = "dev"
            gate = InternalAuthGate.from_env()
            self.assertTrue(gate.check(None, None))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_secure_mode_requires_tokens(self):
        old = dict(os.environ)
        try:
            os.environ.pop("HYDRAI_INTERNAL_TOKENS_JSON", None)
            os.environ.pop("HYDRAI_INTERNAL_TOKEN_ID", None)
            os.environ.pop("HYDRAI_INTERNAL_TOKEN", None)
            os.environ["HYDRAI_SECURITY_MODE"] = "secure"
            with self.assertRaises(AuthError):
                InternalAuthGate.from_env()
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
