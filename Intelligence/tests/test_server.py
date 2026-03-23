import json
import threading
import time
import unittest
import urllib.error
import urllib.request

from intelligence.auth import InternalAuthGate
from intelligence.config import Limits, RouteConfig, ServiceConfig
from intelligence.server import IntelligenceService


class ServerTests(unittest.TestCase):
    def test_invalid_content_length_returns_400(self):
        route = RouteConfig(
            name="embed",
            type="embedding",
            adapter="embedding",
            listen=6199,
            model="fake",
            output_encoding="base64",
            output_dimension=3,
            limits=Limits(max_concurrency=1, timeout_sec=5),
        )
        service = IntelligenceService(ServiceConfig(routes=(route,)), InternalAuthGate(mode="dev", tokens={}))
        service.start()
        try:
            time.sleep(0.1)
            req = urllib.request.Request(
                "http://127.0.0.1:6199/v1/embeddings",
                data=b'{"input":"hello"}',
                headers={"Content-Type": "application/json", "Content-Length": "abc"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 400)
            body = ctx.exception.read().decode()
            self.assertIn("invalid content-length", body)
            ctx.exception.close()
        finally:
            stopper = threading.Thread(target=service.stop)
            stopper.start()
            stopper.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
