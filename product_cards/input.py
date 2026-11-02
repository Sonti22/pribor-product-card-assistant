"""Strict input validation and a source-addressable fact catalogue."""

import json
import re
from dataclasses import dataclass
from typing import Any

from .errors import InputError

MAX_INPUT_BYTES = 32_768
DEFAULT_EXPECTED = (
    "диапазон измерений", "класс точности", "питание", "тип корпуса", "интерфейсы",
)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("В JSON есть повторяющиеся ключи. Удалите дубликаты.")
        result[key] = value
    return result


def parse_json(raw: bytes | str) -> dict:
    try:
        if isinstance(raw, bytes):
            if len(raw) > MAX_INPUT_BYTES:
                raise InputError("Входной JSON превышает 32 КиБ.")
            raw = raw.decode("utf-8-sig")
        if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
            raise InputError("Входной JSON превышает 32 КиБ.")
        result = json.loads(raw, object_pairs_hook=_unique_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(
                                InputError("NaN и Infinity не допускаются в JSON.")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InputError("Нужен корректный JSON в UTF-8 без комментариев и лишних запятых.") from exc
    if not isinstance(result, dict):
        raise InputError("Верхний уровень JSON должен быть объектом одного товара.")
    return result


def _text(value: Any, field: str, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise InputError(f"Поле {field} должно быть строкой или null.")
    if any(ord(char) < 32 and char not in "\t\r\n" for char in value):
        raise InputError(f"Поле {field} содержит управляющие символы.")
    value = " ".join(value.split())
    if required and not value:
        raise InputError(f"Заполните обязательное поле {field}.")
    if len(value) > limit:
        raise InputError(f"Поле {field}: максимум {limit} символов.")
    return value


def pointer_key(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


@dataclass(frozen=True)
class Fact:
    id: str
    label: str
    value: str
    source: str

    @property
    def sentence(self) -> str:
        return f"{self.label}: {self.value}"


@dataclass(frozen=True)
class Product:
    name: str
    manufacturer: str
    specs: dict[str, str]
    description: str
    expected_specs: tuple[str, ...]
    source_note: str

    @classmethod
    def from_dict(cls, data: dict) -> "Product":
        allowed = {"name", "manufacturer", "specs", "description", "expected_specs", "source_note"}
        if set(data) - allowed:
            raise InputError("Неизвестные поля. Разрешены: " + ", ".join(sorted(allowed)) + ".")
        name = _text(data.get("name"), "name", 160, required=True)
        manufacturer = _text(data.get("manufacturer"), "manufacturer", 120)
        description = _text(data.get("description"), "description", 6000)
        source_note = _text(data.get("source_note"), "source_note", 400)
        raw_specs = data.get("specs")
        if raw_specs is None:
            raw_specs = {}
        if not isinstance(raw_specs, dict) or len(raw_specs) > 32:
            raise InputError("specs должен быть объектом, содержащим не более 32 характеристик.")
        specs = {}
        for key, value in raw_specs.items():
            label = _text(key, "ключ specs", 80, required=True)
            if label.casefold() in {k.casefold() for k in specs}:
                raise InputError("В specs есть одинаковые названия после нормализации пробелов/регистра.")
            specs[label] = _text(value, f"specs.{label}", 240)
        expected = data.get("expected_specs", list(DEFAULT_EXPECTED))
        if not isinstance(expected, list) or len(expected) > 32:
            raise InputError("expected_specs должен быть массивом, максимум 32 названия.")
        expected = tuple(_text(k, "expected_specs", 80, required=True) for k in expected)
        if len({k.casefold() for k in expected}) != len(expected):
            raise InputError("В expected_specs есть повторяющиеся названия.")
        return cls(name, manufacturer, specs, description, expected, source_note)

    def spec_facts(self) -> list[Fact]:
        return [Fact(f"s{i}", key, value, "/specs/" + pointer_key(key))
                for i, (key, value) in enumerate(self.specs.items()) if value]

    def description_facts(self) -> list[Fact]:
        # Split only at a sentence boundary followed by a capital letter.
        # Decimal commas/points and compound technical values remain intact.
        pieces = re.split(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z«])", self.description)
        return [Fact(f"d{i}", "Фрагмент описания", text, "/description")
                for i, text in enumerate(pieces) if text]

    def missing_fields(self) -> list[dict]:
        missing = []
        for field, value, label in (("manufacturer", self.manufacturer, "производитель"),
                                    ("description", self.description, "описание / назначение")):
            if not value:
                missing.append({"field": "/" + field, "label": label, "value": "данных нет"})
        known = {key.casefold(): value for key, value in self.specs.items()}
        labels = list(self.expected_specs) + [key for key, value in self.specs.items() if not value]
        seen = set()
        for label in labels:
            if label.casefold() not in seen and not known.get(label.casefold()):
                missing.append({"field": "/specs/" + pointer_key(label), "label": label,
                                "value": "данных нет", "action": "Уточнить значение и применимость к прибору."})
            seen.add(label.casefold())
        return missing
