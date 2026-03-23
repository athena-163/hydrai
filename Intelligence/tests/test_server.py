import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from intelligence.auth import InternalAuthGate
from intelligence.config import Limits, RouteConfig, ServiceConfig
from intelligence.server import IntelligenceService


class ServerTests(unittest.TestCase):
    def test_failed_startup_releases_bound_ports(self):
        route_ok = RouteConfig(
            name="ok",
            type="chat",
            adapter="remote",
            listen=6196,
            model="fake",
            limits=Limits(max_concurrency=1, timeout_sec=5),
        )
        route_fail = RouteConfig(
            name="fail",
            type="chat",
            adapter="llama",
            listen=6197,
            model="fake",
            artifact="/tmp/fake.gguf",
            limits=Limits(max_concurrency=1, timeout_sec=5),
        )

        class _Adapter:
            def __init__(self, route):
                self.route = route

            def startup(self):
                if self.route.name == "fail":
                    raise RuntimeError("boom")

            def shutdown(self):
                return None

            def health(self):
                return {"name": self.route.name}

        with (
            mock.patch("intelligence.server.CONTROL_PORT", 6195),
            mock.patch("intelligence.server.build_adapter", side_effect=lambda route, _backend: _Adapter(route)),
        ):
            service = IntelligenceService(
                ServiceConfig(routes=(route_ok, route_fail), config_path=""),
                InternalAuthGate(mode="dev", tokens={}),
            )
            with self.assertRaises(RuntimeError):
                service.start()

        for port in (6195, 6196, 6197):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))

    def test_help_endpoint_exposes_route_summary(self):
        route = RouteConfig(
            name="embed",
            type="embedding",
            adapter="embedding",
            listen=6198,
            model="fake",
            output_encoding="base64",
            output_dimension=3,
            limits=Limits(max_concurrency=1, timeout_sec=5),
        )
        with mock.patch("intelligence.server.CONTROL_PORT", 6194):
            service = IntelligenceService(
                ServiceConfig(routes=(route,), config_path="/Users/zeus/Public/hydrai/Intelligence.json"),
                InternalAuthGate(mode="dev", tokens={}),
            )
            service.start()
            try:
                time.sleep(0.1)
                payload = json.loads(urllib.request.urlopen("http://127.0.0.1:6194/help", timeout=5).read().decode())
                self.assertEqual(payload["control_port"], 6194)
                self.assertEqual(payload["config_path"], "/Users/zeus/Public/hydrai/Intelligence.json")
                self.assertEqual(payload["routes"][0]["listen"], 6198)
            finally:
                stopper = threading.Thread(target=service.stop)
                stopper.start()
                stopper.join(timeout=5)

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
        with mock.patch("intelligence.server.CONTROL_PORT", 6193):
            service = IntelligenceService(ServiceConfig(routes=(route,), config_path=""), InternalAuthGate(mode="dev", tokens={}))
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

    def test_unhandled_route_exception_returns_500_json(self):
        route = RouteConfig(
            name="embed",
            type="embedding",
            adapter="embedding",
            listen=6200,
            model="fake",
            output_encoding="base64",
            output_dimension=3,
            limits=Limits(max_concurrency=1, timeout_sec=5),
        )

        class _BrokenAdapter:
            def startup(self):
                return None

            def shutdown(self):
                return None

            def health(self):
                return {"name": "broken"}

            def embeddings(self, _body):
                raise RuntimeError("boom")

        with (
            mock.patch("intelligence.server.CONTROL_PORT", 6192),
            mock.patch("intelligence.server.build_adapter", return_value=_BrokenAdapter()),
        ):
            service = IntelligenceService(ServiceConfig(routes=(route,), config_path=""), InternalAuthGate(mode="dev", tokens={}))
            service.start()
            try:
                time.sleep(0.1)
                req = urllib.request.Request(
                    "http://127.0.0.1:6200/v1/embeddings",
                    data=b'{"input":"hello"}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5)
                self.assertEqual(ctx.exception.code, 500)
                body = ctx.exception.read().decode()
                self.assertIn("internal server error", body)
                ctx.exception.close()
            finally:
                stopper = threading.Thread(target=service.stop)
                stopper.start()
                stopper.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
