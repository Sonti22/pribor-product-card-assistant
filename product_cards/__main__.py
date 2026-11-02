import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .errors import CardError
from .export import to_markdown
from .generate import generate
from .input import MAX_INPUT_BYTES, Product, parse_json
from .llm import OllamaClient


def _write_atomic(path: Path, content: str) -> None:
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, delete=False, suffix=".tmp") as handle:
            temp = Path(handle.name)
            handle.write(content)
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Черновик B2B-карточки через локальный Ollama API.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Путь к JSON или - для stdin")
    source.add_argument("--serve", action="store_true", help="Открыть локальный HTTP-сервис и форму")
    parser.add_argument("--port", type=int, default=8080, help="Порт локальной формы (по умолчанию 8080)")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="UTF-8 файл результата; по умолчанию stdout")
    parser.add_argument("--model", help="Локальная модель Ollama; по умолчанию OLLAMA_MODEL / qwen2.5:7b")
    args = parser.parse_args(argv)
    try:
        if args.serve:
            from .server import serve
            serve(args.port, args.model)
            return 0
        if args.input == "-":
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        else:
            input_path = Path(args.input)
            if args.output and input_path.resolve() == args.output.resolve():
                raise CardError("file_error", "Входной файл и файл результата должны отличаться.")
            with input_path.open("rb") as handle:
                raw = handle.read(MAX_INPUT_BYTES + 1)
        product = Product.from_dict(parse_json(raw))
        if args.output and not args.output.parent.is_dir():
            raise CardError("file_error", "Папка результата не существует. Создайте её перед запуском.")
        card = generate(product, OllamaClient(model=args.model))
        content = (json.dumps(card, ensure_ascii=False, indent=2) + "\n"
                   if args.format == "json" else to_markdown(card))
        if args.output:
            _write_atomic(args.output, content)
        else:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            sys.stdout.write(content)
        return 0
    except CardError as exc:
        error = {"error": {"code": exc.code, "message": exc.message}}
    except (OSError, UnicodeError):
        error = {"error": {"code": "file_error", "message": "Не удалось прочитать вход или сохранить результат. Проверьте путь и права доступа."}}
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    sys.stderr.write(json.dumps(error, ensure_ascii=False) + "\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
