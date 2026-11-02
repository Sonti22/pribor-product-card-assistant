import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from product_cards.errors import CardError
from product_cards.llm import OllamaClient
from test_cards import load_product, valid_plan


class Handler(BaseHTTPRequestHandler):
    response_bytes = b""
    request_data = None
    status_code = 200

    def do_POST(self):
        Handler.request_data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(Handler.status_code)
        self.send_header("Content-Type", "application/json")
        if Handler.status_code == 302:
            self.send_header("Location", "http://example.invalid/should-never-be-requested")
        self.end_headers()
        self.wfile.write(Handler.response_bytes)

    def log_message(self, *args):
        pass


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        Handler.status_code = 200
        Handler.response_bytes = b""

    def test_real_http_round_trip_uses_schema_and_returns_plan(self):
        p = load_product()
        Handler.response_bytes = json.dumps({"done": True, "done_reason": "stop", "model": "fixture",
                                            "message": {"content": json.dumps(valid_plan(p))}}).encode()
        plan, metadata = OllamaClient(url=self.url).generate_plan(p)
        self.assertEqual(plan, valid_plan(p))
        self.assertEqual(metadata["reported_model"], "fixture")
        self.assertIs(Handler.request_data["stream"], False)
        self.assertEqual(Handler.request_data["format"]["properties"]["description_id"]["enum"], ["d0", None])
        self.assertEqual(Handler.request_data["options"]["temperature"], 0)

    def test_invalid_or_truncated_response_is_not_a_card(self):
        for envelope in ("not json", {}, {"done": False}, {"done": True, "done_reason": "length"},
                         {"done": True, "message": {"content": "[]"}},
                         {"done": True, "message": {"content": '{"x":1,"x":2}'}}):
            with self.subTest(envelope=envelope):
                Handler.response_bytes = json.dumps(envelope).encode()
                with self.assertRaises(CardError) as caught:
                    OllamaClient(url=self.url).generate_plan(load_product())
                self.assertEqual(caught.exception.code, "llm_invalid_response")

    def test_response_size_is_bounded(self):
        Handler.response_bytes = b" " * 131073
        with self.assertRaises(CardError) as caught:
            OllamaClient(url=self.url).generate_plan(load_product())
        self.assertEqual(caught.exception.code, "llm_invalid_response")

    def test_redirect_is_not_followed(self):
        Handler.status_code = 302
        with self.assertRaises(CardError) as caught:
            OllamaClient(url=self.url).generate_plan(load_product())
        self.assertEqual(caught.exception.code, "llm_http_error")

    def test_http_errors_do_not_echo_provider_body(self):
        for status in (401, 403, 404, 429, 500, 503):
            with self.subTest(status=status):
                Handler.status_code = status
                Handler.response_bytes = b"private-provider-diagnostic"
                with self.assertRaises(CardError) as caught:
                    OllamaClient(url=self.url).generate_plan(load_product())
                self.assertEqual(caught.exception.code, "llm_http_error")
                self.assertNotIn("private-provider-diagnostic", str(caught.exception))

    def test_timeout_and_connection_error_are_actionable(self):
        for error, code in ((socket.timeout(), "llm_timeout"), (URLError("private-diagnostic"), "llm_unavailable")):
            with self.subTest(code=code):
                client = OllamaClient(url=self.url)
                client.opener = Mock()
                client.opener.open.side_effect = error
                with self.assertRaises(CardError) as caught:
                    client.generate_plan(load_product())
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("private-diagnostic", str(caught.exception))

    def test_remote_urls_and_invalid_settings_are_rejected(self):
        for url in ("https://api.example.com", "http://127.0.0.1/extra", "http://user:password@localhost",
                    "http://localhost?key=secret", "http://127.0.0.1:bad"):
            with self.subTest(url=url), self.assertRaises(CardError):
                OllamaClient(url=url)
        for timeout in (0, -1, 601, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(CardError):
                OllamaClient(timeout=timeout)
        with self.assertRaises(CardError):
            OllamaClient(model="qwen-cloud")


if __name__ == "__main__":
    unittest.main()
