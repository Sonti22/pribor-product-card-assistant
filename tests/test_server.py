import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from product_cards.generate import render_card
from product_cards.server import make_server
from test_cards import load_product, valid_plan


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def post(self, raw=b'{"name":"test"}', **headers):
        return urlopen(Request(self.url + "/api/generate", data=raw,
                               headers={"Content-Type": "application/json", **headers}), timeout=5)

    def test_form_and_static_assets_load(self):
        for path in ("/", "/app.js", "/style.css"):
            with self.subTest(path=path), urlopen(self.url + path) as response:
                self.assertEqual(response.status, 200)
                self.assertGreater(len(response.read()), 100)
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_generation_returns_json_and_markdown(self):
        p = load_product()
        card = render_card(p, valid_plan(p), {"model": "fixture"})
        with patch("product_cards.server.generate", return_value=card):
            with self.post() as response:
                data = json.load(response)
        self.assertEqual(data["card"]["seo_title"], card["seo_title"])
        self.assertIn("## SEO-описание", data["markdown"])

    def test_bad_json_never_calls_generation(self):
        with patch("product_cards.server.generate") as generate:
            with self.assertRaises(HTTPError) as caught:
                self.post(b"{bad")
            with caught.exception as response:
                self.assertEqual(response.code, 400)
                self.assertEqual(json.load(response)["error"]["code"], "invalid_input")
            generate.assert_not_called()

    def test_untrusted_origin_is_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            self.post(Origin="https://example.invalid")
        with caught.exception as response:
            self.assertEqual(response.code, 403)

    def test_large_input_is_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            self.post(b"x" * 32769)
        with caught.exception as response:
            self.assertEqual(response.code, 413)

    def test_wrong_content_type_is_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            self.post(**{"Content-Type": "text/plain"})
        with caught.exception as response:
            self.assertEqual(response.code, 415)


if __name__ == "__main__":
    unittest.main()
