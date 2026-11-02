"""Generate both deliverable examples through the real local Ollama API."""

import json
import sys
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from product_cards.export import to_markdown
from product_cards.generate import generate
from product_cards.input import Product, parse_json
from product_cards.llm import OllamaClient


def main():
    client = OllamaClient()
    output = ROOT / "examples" / "outputs"
    output.mkdir(exist_ok=True)
    # Record a model digest when available, without changing card generation.
    with build_opener(ProxyHandler({})).open(client.url + "/api/tags", timeout=10) as response:
        tags = json.load(response)
    model_info = next((m for m in tags["models"] if m["name"] == client.model), {})
    for stem in ("manometer", "demo_thermometer"):
        p = Product.from_dict(parse_json((ROOT / "examples" / "inputs" / f"{stem}.json").read_bytes()))
        card = generate(p, client)
        card["generation"]["model_digest"] = model_info.get("digest")
        (output / f"{stem}.json").write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / f"{stem}.md").write_text(to_markdown(card), encoding="utf-8")
        print(json.dumps({"example": stem, "counts": card["character_counts"],
                          "attempts": card["generation"]["attempts"],
                          "model": card["generation"]["model"]}), flush=True)


if __name__ == "__main__":
    main()
