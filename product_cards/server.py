"""Local-only, single-generation-at-a-time prototype; not a production server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .errors import CardError
from .export import to_markdown
from .generate import generate
from .input import MAX_INPUT_BYTES, Product, parse_json
from .llm import OllamaClient


def make_server(port: int, model: str | None = None) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise CardError("configuration_error", "Порт должен быть числом от 0 до 65535.")
    client = OllamaClient(model=model)
    gate = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def send_data(self, status: int, data: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def json(self, status: int, data: dict):
            self.send_data(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def local_request(self):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            if self.headers.get("Host") not in hosts or (origin and origin not in {"http://" + h for h in hosts}):
                self.json(403, {"error": {"code": "forbidden_origin", "message": "Форма доступна только с локального адреса."}})
                return False
            return True

        def do_GET(self):
            if not self.local_request():
                return
            paths = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
            if self.path not in paths:
                self.json(404, {"error": {"code": "not_found", "message": "Страница не найдена."}})
                return
            filename, mime = paths[self.path]
            self.send_data(200, (Path(__file__).parent / "static" / filename).read_bytes(), mime + "; charset=utf-8")

        def do_POST(self):
            if not self.local_request():
                return
            if self.path != "/api/generate":
                self.json(404, {"error": {"code": "not_found", "message": "Endpoint не найден."}})
                return
            if self.headers.get_content_type() != "application/json":
                self.json(415, {"error": {"code": "invalid_content_type", "message": "Используйте Content-Type: application/json."}})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = 0
            if not 0 < size <= MAX_INPUT_BYTES or self.headers.get("Transfer-Encoding"):
                self.json(413, {"error": {"code": "invalid_size", "message": "Нужен JSON размером от 1 байта до 32 КиБ с Content-Length."}})
                return
            try:
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise CardError("invalid_input", "Тело запроса получено не полностью.")
                product = Product.from_dict(parse_json(raw))
            except (TimeoutError, OSError):
                self.json(408, {"error": {"code": "request_timeout", "message": "Не удалось получить JSON вовремя."}})
                return
            except CardError as exc:
                self.json(400, {"error": {"code": exc.code, "message": exc.message}})
                return
            if not gate.acquire(blocking=False):
                self.json(429, {"error": {"code": "busy", "message": "Генерация уже выполняется. Дождитесь результата."}})
                return
            try:
                card = generate(product, client)
                self.json(200, {"card": card, "markdown": to_markdown(card)})
            except CardError as exc:
                self.json(502, {"error": {"code": exc.code, "message": exc.message}})
            finally:
                gate.release()

        def log_message(self, *args):
            # Do not log product data or raw request lines.
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port: int = 8080, model: str | None = None):
    server = make_server(port, model)
    print(f"Product cards: http://127.0.0.1:{server.server_port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
