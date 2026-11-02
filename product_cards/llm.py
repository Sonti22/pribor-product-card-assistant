"""Small Ollama HTTP adapter with bounded requests and safe errors."""

import json
import math
import os
import socket
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from .errors import CardError
from .input import Product, parse_json
from .prompts import messages, plan_schema

MAX_RESPONSE_BYTES = 131_072


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OllamaClient:
    def __init__(self, url: str | None = None, model: str | None = None,
                 timeout: float | None = None):
        self.url = (url or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        try:
            self.timeout = float(timeout if timeout is not None else os.getenv("OLLAMA_TIMEOUT", "180"))
            parsed = urlsplit(self.url)
            port = parsed.port
        except ValueError as exc:
            raise CardError("configuration_error", "Проверьте OLLAMA_URL и числовой OLLAMA_TIMEOUT.") from exc
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path or (port is not None and port < 1)):
            raise CardError("configuration_error", "OLLAMA_URL должен указывать на локальный HTTP-сервер без пути и учётных данных.")
        if not math.isfinite(self.timeout) or not 1 <= self.timeout <= 600:
            raise CardError("configuration_error", "OLLAMA_TIMEOUT должен быть от 1 до 600 секунд.")
        if not self.model.strip() or len(self.model) > 120 or self.model.endswith(":cloud") or "-cloud" in self.model:
            raise CardError("configuration_error", "Укажите имя локальной модели в OLLAMA_MODEL.")
        # Keep product data on localhost, independent of HTTP_PROXY environment variables.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def generate_plan(self, product: Product, correction: str | None = None) -> tuple[dict, dict]:
        prompt = messages(product)
        if correction:
            prompt.append({"role": "user", "content": "Предыдущий план не прошёл проверку: " + correction +
                           " Построй новый корректный план по исходному каталогу. Только JSON."})
        payload = {"model": self.model, "messages": prompt, "stream": False,
                   "format": plan_schema(product),
                   "options": {"temperature": 0, "seed": 42, "num_predict": 768, "num_ctx": 8192}}
        request = Request(self.url + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            if exc.code == 404:
                message = "Модель или endpoint не найдены. Проверьте ollama list и выполните ollama pull для выбранной модели."
            elif exc.code == 429:
                message = "Ollama временно ограничила запросы. Повторите позже."
            elif exc.code in (401, 403):
                message = "Ollama отказала в доступе. Проверьте локальную конфигурацию."
            else:
                message = f"Ollama вернула HTTP {exc.code}. Проверьте состояние локального сервера."
            raise CardError("llm_http_error", message) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise CardError("llm_timeout", "Ollama не ответила вовремя. Проверьте модель или увеличьте OLLAMA_TIMEOUT.") from exc
        except (URLError, OSError, HTTPException) as exc:
            raise CardError("llm_unavailable", "Не удалось связаться с Ollama. Запустите ollama serve и проверьте OLLAMA_URL.") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise CardError("llm_invalid_response", "Ответ Ollama слишком большой.")
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or envelope.get("done") is not True:
                raise ValueError("incomplete")
            if envelope.get("done_reason") not in (None, "stop"):
                raise ValueError("generation stopped early")
            if not isinstance(envelope.get("message"), dict):
                raise ValueError("missing message")
            content = envelope["message"].get("content")
            if not isinstance(content, str):
                raise ValueError("missing text")
            plan = parse_json(content)
        except (ValueError, TypeError, UnicodeError, RecursionError, CardError) as exc:
            raise CardError("llm_invalid_response", "Ollama вернула неполный или некорректный JSON. Черновик не создан.") from exc
        metadata = {"provider": "ollama", "model": self.model,
                    "reported_model": envelope.get("model", self.model)}
        for key in ("total_duration", "prompt_eval_count", "eval_count"):
            if isinstance(envelope.get(key), int):
                metadata[key] = envelope[key]
        return plan, metadata
